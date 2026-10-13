"""规章制度生成业务逻辑（需求 ⑧）：大纲 → 全文 → 自动合规审查 → 修正循环。

Dify 侧只做单轮生成（mode=outline / mode=document），循环与进度都在后端：
    生成首版 → 逐块审查 → 不合规则把冲突清单 + 上一版全文回传重新生成 → 再审查，最多 3 轮
只回传冲突清单而不给上一版全文会让模型整篇重写、可能引入新冲突而导致循环不收敛，
因此修正必须带 previous_sections（见 dify/README.md）。
"""

import json
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    REVIEW_STATUS_COMPLETED,
    REVIEW_STATUS_FAILED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_RUNNING,
    REVIEW_TYPE_REGULATION,
)
from app.core.exceptions import BizError, NotFoundError
from app.models.base import SessionLocal
from app.models.generation import GenerationTask
from app.services import review as review_service
from app.services import word_generator
from app.services.dify import dify_client

MODE_OUTLINE = "outline"
MODE_DOCUMENT = "document"
# 回传给模型的冲突条数上限（避免噪音淹没重点）
MAX_CONFLICTS_FEEDBACK = 15

# 任务阶段（前端据此切换进度条形态：写作中=动效，审查中=确定进度）
PHASE_GENERATING = "generating"
PHASE_REVIEWING = "reviewing"
PHASE_DONE = "done"


def _api_key() -> str:
    return settings.DIFY_GENERATE_APP_KEY or settings.DIFY_API_KEY


def _update(db: Session, task: GenerationTask, **fields) -> None:
    for key, value in fields.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)


async def generate_outline(requirement: str, user: str) -> str:
    """生成大纲（mode=outline），同步返回可编辑的大纲文本。"""
    if not requirement.strip():
        raise BizError(message="请填写规章制度的内容需求")
    result = await dify_client.run_workflow(
        api_key=_api_key(),
        inputs={"requirement": requirement, "mode": MODE_OUTLINE},
        user=user,
    )
    outputs = (result.get("data") or {}).get("outputs") or {}
    outline = str(outputs.get("outline_text") or "").strip()
    if not outline:
        raise BizError(message="大纲生成失败，请重试")
    return outline


async def _generate_document(
    requirement: str,
    outline: str,
    user: str,
    previous_sections: str | None = None,
    review_conflicts: str | None = None,
    revision_round: int | None = None,
) -> list[dict]:
    """生成/修正全文（mode=document），返回章节列表。"""
    inputs: dict = {"requirement": requirement, "mode": MODE_DOCUMENT, "outline": outline}
    if previous_sections:
        inputs["previous_sections"] = previous_sections
    if review_conflicts:
        inputs["review_conflicts"] = review_conflicts
    if revision_round:
        inputs["revision_round"] = revision_round

    result = await dify_client.run_workflow(api_key=_api_key(), inputs=inputs, user=user)
    outputs = (result.get("data") or {}).get("outputs") or {}
    sections_json = str(outputs.get("sections_json") or "").strip()
    if not sections_json:
        raise BizError(message="全文生成失败，请重试")
    try:
        data = json.loads(sections_json)
    except json.JSONDecodeError as exc:
        raise BizError(message=f"全文结构解析失败：{exc}") from exc
    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list) or not sections:
        raise BizError(message="全文结构为空，请重试")
    return sections


def _sections_to_text(sections: list[dict]) -> str:
    return "\n".join(
        f"{str(s.get('title') or '').strip()}\n{str(s.get('content') or '').strip()}".strip()
        for s in sections
    )


def _conflicts_for_feedback(review: dict) -> str:
    """把审查结果整理成回传模型的冲突清单（去重已在 merge_risks 完成，这里截断条数）。"""
    risks = review.get("risks") or []
    items = []
    for risk in risks[:MAX_CONFLICTS_FEEDBACK]:
        items.append(
            {
                "clause": risk.get("clause"),
                "risk_level": risk.get("risk_level"),
                "violations": risk.get("violations") or [],
                "analysis": risk.get("analysis") or "",
                "citations": risk.get("citations") or [],
                "needs_review": bool(risk.get("needs_review")),
                "suggestion": risk.get("suggestion"),
            }
        )
    return json.dumps(items, ensure_ascii=False)


def create_task(db: Session, *, requirement: str, outline: str | None, created_by: str | None) -> GenerationTask:
    if not requirement.strip():
        raise BizError(message="请填写规章制度的内容需求")
    task = GenerationTask(
        requirement=requirement,
        outline=outline,
        status=REVIEW_STATUS_PENDING,
        created_by=created_by,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> GenerationTask:
    task = db.get(GenerationTask, task_id)
    if task is None:
        raise NotFoundError("生成任务不存在")
    return task


def parse_review(task: GenerationTask) -> dict | None:
    if not task.review_json:
        return None
    try:
        return json.loads(task.review_json)
    except json.JSONDecodeError:
        return None


def parse_sections(task: GenerationTask) -> list[dict]:
    if not task.sections_json:
        return []
    try:
        data = json.loads(task.sections_json)
    except json.JSONDecodeError:
        return []
    sections = data.get("sections") if isinstance(data, dict) else None
    return sections if isinstance(sections, list) else []


def delete_task(db: Session, task: GenerationTask) -> None:
    from pathlib import Path

    if task.doc_path:
        Path(task.doc_path).unlink(missing_ok=True)
    db.delete(task)
    db.commit()


async def run_regulation_task(task_id: int) -> None:
    """后台执行：生成首版 → 逐块审查 → 不合规则带冲突与上一版全文修正，最多 max_rounds 轮。"""
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if task is None:
            return
        _update(db, task, status=REVIEW_STATUS_RUNNING, error=None, phase=PHASE_GENERATING)
        user = task.created_by or "generation"
        outline = task.outline or ""

        sections = await _generate_document(task.requirement, outline, user)
        _update(db, task, sections_json=json.dumps({"sections": sections}, ensure_ascii=False))

        round_no = 0
        review: dict = {}
        while True:
            # 每轮审查：进度通过 phase / review_round / completed_chunks 回传
            _update(
                db,
                task,
                phase=PHASE_REVIEWING,
                review_round=round_no + 1,
                completed_chunks=0,
                failed_chunks=0,
            )

            def on_start(total: int) -> None:
                """解析出块数后立即回填，前端从审查一开始就能显示 i/n。"""
                task.total_chunks = total
                task.completed_chunks = 0
                task.failed_chunks = 0
                db.commit()

            def on_progress(completed: int, total: int, failed: int) -> None:
                task.total_chunks = total
                task.completed_chunks = completed
                task.failed_chunks = failed
                db.commit()

            review = await review_service.review_text(
                _sections_to_text(sections), REVIEW_TYPE_REGULATION, user, on_progress, on_start
            )
            _update(
                db,
                task,
                is_compliant=review["is_compliant"],
                summary=review["summary"],
                review_json=json.dumps(review, ensure_ascii=False),
            )

            if review["is_compliant"] or round_no >= task.max_rounds:
                break

            round_no += 1
            _update(db, task, round=round_no, phase=PHASE_GENERATING)
            sections = await _generate_document(
                task.requirement,
                outline,
                user,
                previous_sections=_sections_to_text(sections),
                review_conflicts=_conflicts_for_feedback(review),
                revision_round=round_no,
            )
            _update(db, task, sections_json=json.dumps({"sections": sections}, ensure_ascii=False))

        # 落 Word（python-docx 程序化排版，无固定模板）
        # 注意：不把用户的需求提示词写进文档，文档只包含规章制度正文（章节标题 + 条款）
        output_dir = word_generator.ensure_output_dir(settings.OUTPUT_DIR)
        doc_name = word_generator.safe_filename(f"规章制度_{task.requirement[:20]}")
        doc_path = str(output_dir / doc_name)
        word_generator.build_docx_from_sections(sections, doc_path)

        _update(
            db,
            task,
            status=REVIEW_STATUS_COMPLETED,
            phase=PHASE_DONE,
            doc_path=doc_path,
            doc_name=doc_name,
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务异常必须落库，否则会永远停在 running
        task = db.get(GenerationTask, task_id)
        if task is not None:
            _update(db, task, status=REVIEW_STATUS_FAILED, phase=PHASE_DONE, error=str(exc)[:500])
    finally:
        db.close()
