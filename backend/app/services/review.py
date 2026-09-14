"""审查业务编排（需求 ②③）：解析 → 切块 → 逐块调 Dify 工作流 → 代码合并。

职责划分：
- Dify 只做「单块审查」，不长文档循环；
- 块级控制、进度、并发、结果合并都在后端（设计文档第 5 节），便于观测与恢复；
- 合同审查与规章制度审查复用同一管线，仅按 review_type 选择不同的 Dify 应用 Key。
"""

import asyncio
import difflib
import json
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    REVIEW_STATUS_COMPLETED,
    REVIEW_STATUS_FAILED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_RUNNING,
    REVIEW_TYPE_CONTRACT,
    REVIEW_TYPE_REGULATION,
    RISK_LEVEL_ORDER,
)
from app.core.exceptions import BizError, NotFoundError
from app.models.base import SessionLocal
from app.models.review import ReviewTask
from app.services import document_parser
from app.services.dify import dify_client

# 逐块调用的并发度：Dify 与上游模型都有速率限制，3 是速度与稳定性的折中
CHUNK_CONCURRENCY = 3
# 跨块合并时判定「同一风险」的条款文本相似度阈值
CLAUSE_SIMILARITY_THRESHOLD = 0.7
# merge_risks 回传/展示的条款原文截断长度
CLAUSE_PREVIEW_LEN = 60


def review_app_key(review_type: str) -> str:
    """按审查类型选择 Dify 应用 Key（合同审查 / 制度审查为两个独立应用）。"""
    if review_type == REVIEW_TYPE_REGULATION:
        return settings.DIFY_REGULATION_REVIEW_APP_KEY or settings.DIFY_API_KEY
    return settings.DIFY_CONTRACT_REVIEW_APP_KEY or settings.DIFY_API_KEY


def _normalize(text: str) -> str:
    """去空白与常见标点，用于条款文本比对。"""
    return "".join(ch for ch in (text or "") if ch.isalnum())


def _violation_keys(risk: dict) -> set[tuple[str, str]]:
    keys = set()
    for item in risk.get("violations") or []:
        if not isinstance(item, dict):
            continue
        law = _normalize(str(item.get("law_name") or ""))
        article = _normalize(str(item.get("article") or ""))
        if law or article:
            keys.add((law, article))
    return keys


def _clause_similar(a: str, b: str) -> bool:
    left, right = _normalize(a), _normalize(b)
    if not left or not right:
        return False
    if left == right:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= CLAUSE_SIMILARITY_THRESHOLD


def _merge_violations(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """按 (law_name, article) 合并违反条款，保留描述更完整的一条。"""
    merged = list(existing)
    seen = {_normalize(str(v.get("law_name") or "")) + _normalize(str(v.get("article") or "")) for v in merged}
    for item in incoming or []:
        if not isinstance(item, dict):
            continue
        key = _normalize(str(item.get("law_name") or "")) + _normalize(str(item.get("article") or ""))
        if key and key not in seen:
            merged.append(item)
            seen.add(key)
        elif key in seen:
            # 同一条款重复出现：取描述更长的一条
            for i, cur in enumerate(merged):
                cur_key = _normalize(str(cur.get("law_name") or "")) + _normalize(str(cur.get("article") or ""))
                if cur_key == key and len(str(item.get("description") or "")) > len(
                    str(cur.get("description") or "")
                ):
                    merged[i] = item
    return merged


def _risk_level_rank(level: str) -> int:
    return RISK_LEVEL_ORDER.get(str(level or "").lower(), len(RISK_LEVEL_ORDER))


def merge_risks(chunks: list[dict], review_type: str) -> list[dict]:
    """合并跨块的风险：去重（同一处条款/同一法条）→ 回填定位 → 排序。

    chunks 元素形如 {"chunk_index": 1, "location": "第 3 页", "risks": [...]}。
    """
    merged: list[dict] = []

    for chunk in chunks:
        for risk in chunk.get("risks") or []:
            if not isinstance(risk, dict):
                continue
            clause = str(risk.get("clause") or "")
            keys = _violation_keys(risk)
            # 制度审查无案例库，reference_case 一律不保留（避免上游误传）
            case_value = (
                risk.get("reference_case")
                if review_type == REVIEW_TYPE_CONTRACT
                else None
            )

            target = None
            for item in merged:
                if keys and keys & _violation_keys(item):
                    target = item
                    break
                if _clause_similar(clause, str(item.get("clause") or "")):
                    target = item
                    break

            if target is None:
                merged.append(
                    {
                        "clause": clause,
                        "risk_level": str(risk.get("risk_level") or "medium").lower(),
                        "violations": _merge_violations([], risk.get("violations") or []),
                        "reference_case": case_value,
                        "suggestion": str(risk.get("suggestion") or ""),
                        "chunk_index": chunk.get("chunk_index"),
                        "location": chunk.get("location") or "",
                    }
                )
                continue

            # 同一风险跨块出现：合并依据、取更高风险等级与更完整的建议
            target["violations"] = _merge_violations(
                target.get("violations") or [], risk.get("violations") or []
            )
            if _risk_level_rank(risk.get("risk_level")) < _risk_level_rank(target.get("risk_level")):
                target["risk_level"] = str(risk.get("risk_level") or "").lower()
            if len(str(risk.get("suggestion") or "")) > len(str(target.get("suggestion") or "")):
                target["suggestion"] = str(risk.get("suggestion") or "")
            if not target.get("reference_case") and case_value:
                target["reference_case"] = case_value
            if not target.get("location"):
                target["location"] = chunk.get("location") or ""

    merged.sort(
        key=lambda item: (
            _risk_level_rank(item.get("risk_level")),
            item.get("chunk_index") or 0,
        )
    )
    return merged


async def review_text(
    text: str, review_type: str, user: str = "review", on_progress=None, on_start=None
) -> dict:
    """对一段文本执行完整审查（解析切块 → 逐块审查 → 合并）。

    供审查任务与「规章制度生成后的自动审查」共用，避免重复实现块级控制。
    on_start(total) 在解析完切块后立即回调（前端可提前显示总块数），
    on_progress(completed, total, failed) 用于汇报进度（同步回调）。
    """
    parsed = document_parser.merge_short_document(document_parser.parse_text(text))
    if on_start:
        on_start(len(parsed.chunks))
    if not parsed.chunks:
        return {
            "is_compliant": True,
            "summary": "文档内容为空，未发现可审查条款。",
            "total_chunks": 0,
            "failed_chunks": 0,
            "risks": [],
        }

    api_key = review_app_key(review_type)
    semaphore = asyncio.Semaphore(CHUNK_CONCURRENCY)
    tasks = [
        asyncio.create_task(_review_chunk(semaphore, api_key, chunk, user))
        for chunk in parsed.chunks
    ]

    results: list[dict] = []
    completed = failed = 0
    for coro in asyncio.as_completed(tasks):
        item = await coro
        results.append(item)
        if item["failed"]:
            failed += 1
        else:
            completed += 1
        if on_progress:
            on_progress(completed, len(parsed.chunks), failed)

    results.sort(key=lambda item: item.get("chunk_index") or 0)
    risks = merge_risks(results, review_type)
    return {
        "is_compliant": not risks and failed == 0,
        "summary": build_summary(risks, len(parsed.chunks), failed),
        "total_chunks": len(parsed.chunks),
        "failed_chunks": failed,
        "risks": risks,
    }


def build_summary(risks: list[dict], total_chunks: int, failed_chunks: int) -> str:
    """生成整体审查结论（代码模板生成，不额外调 LLM）。"""
    if not risks:
        text = f"共审查 {total_chunks} 个文本块，未发现违法违规风险条款。"
    else:
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in risks:
            level = str(item.get("risk_level") or "").lower()
            if level in counts:
                counts[level] += 1
        parts = []
        if counts["high"]:
            parts.append(f"高风险 {counts['high']} 处")
        if counts["medium"]:
            parts.append(f"中风险 {counts['medium']} 处")
        if counts["low"]:
            parts.append(f"低风险 {counts['low']} 处")
        detail = "、".join(parts) or f"{len(risks)} 处"
        text = f"共审查 {total_chunks} 个文本块，发现 {len(risks)} 处风险（{detail}）。"
    if failed_chunks:
        text += f" 其中 {failed_chunks} 个文本块审查失败，建议人工复核。"
    return text


async def _review_chunk(
    semaphore: asyncio.Semaphore, api_key: str, chunk: document_parser.TextChunk, user: str
) -> dict:
    """审查单个块；失败时不中断整体任务，标记该块失败。

    合规产品不能把「解析失败」当成「无风险」：以下两种情形都标记为失败块，
    由整体结论提示人工复核——
    1. 工作流传回 parse_error=true（违规分析输出被截断/无法解析）；
    2. 判定为不合规但没有风险明细（结果自相矛盾）。
    """
    async with semaphore:
        try:
            result = await dify_client.run_workflow(
                api_key=api_key,
                inputs={"chunk_text": chunk.text},
                user=user,
            )
            outputs = (result.get("data") or {}).get("outputs") or {}
            risks = outputs.get("risks")
            risks = risks if isinstance(risks, list) else []
            is_compliant = str(outputs.get("is_compliant", "false")).lower() == "true"
            parse_error = str(outputs.get("parse_error", "false")).lower() == "true"

            if parse_error or (not is_compliant and not risks):
                return {
                    "chunk_index": chunk.chunk_index,
                    "location": chunk.location,
                    "risks": [],
                    "failed": True,
                    "error": "审查结果解析失败或风险明细缺失，需人工复核",
                }
            return {
                "chunk_index": chunk.chunk_index,
                "location": chunk.location,
                "is_compliant": is_compliant,
                "reason": outputs.get("compliance_reason") or "",
                "risks": risks,
                "failed": False,
            }
        except Exception as exc:  # noqa: BLE001 - 单块失败要保留其余块的审查结果
            return {
                "chunk_index": chunk.chunk_index,
                "location": chunk.location,
                "risks": [],
                "failed": True,
                "error": str(exc)[:300],
            }


def _update(db: Session, task: ReviewTask, **fields) -> None:
    for key, value in fields.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)


async def run_review_task(task_id: int, source_text: str | None = None) -> None:
    """后台执行审查任务（FastAPI BackgroundTasks 调用）。

    source_text 为空时从任务记录的 source_path 读取文件。
    """
    db = SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        if task is None:
            return
        _update(db, task, status=REVIEW_STATUS_RUNNING, error=None)

        # 1. 解析 + 切块（短文档按阈值合并为单块）
        try:
            if source_text is not None:
                parsed = document_parser.parse_text(source_text)
            else:
                parsed = document_parser.parse_file(task.source_path or "")
            parsed = document_parser.merge_short_document(parsed)
        except Exception as exc:  # noqa: BLE001
            _update(db, task, status=REVIEW_STATUS_FAILED, error=f"文档解析失败：{exc}")
            return

        if not parsed.chunks:
            _update(db, task, status=REVIEW_STATUS_COMPLETED, is_compliant=True,
                    summary="文档内容为空，未发现可审查条款。")
            return

        _update(db, task, total_chunks=len(parsed.chunks))

        # 2. 逐块审查（限并发，保证进度可观测）
        api_key = review_app_key(task.review_type)
        semaphore = asyncio.Semaphore(CHUNK_CONCURRENCY)
        chunk_results: list[dict] = []
        completed = 0
        failed = 0

        tasks = [
            asyncio.create_task(_review_chunk(semaphore, api_key, chunk, task.created_by or "review"))
            for chunk in parsed.chunks
        ]
        for coro in asyncio.as_completed(tasks):
            item = await coro
            chunk_results.append(item)
            if item["failed"]:
                failed += 1
            else:
                completed += 1
            _update(db, task, completed_chunks=completed, failed_chunks=failed)

        chunk_results.sort(key=lambda item: item.get("chunk_index") or 0)

        # 3. 合并（跨块去重、排序、生成结论）
        risks = merge_risks(chunk_results, task.review_type)
        # 所有块均合规且无失败块，才判定整体合规
        is_compliant = not risks and failed == 0
        summary = build_summary(risks, len(parsed.chunks), failed)
        result = {
            "is_compliant": is_compliant,
            "summary": summary,
            "total_chunks": len(parsed.chunks),
            "failed_chunks": failed,
            "risks": risks,
        }
        _update(
            db,
            task,
            status=REVIEW_STATUS_COMPLETED,
            is_compliant=is_compliant,
            summary=summary,
            result_json=json.dumps(result, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务异常必须落库，否则任务会永远停在 running
        task = db.get(ReviewTask, task_id)
        if task is not None:
            _update(db, task, status=REVIEW_STATUS_FAILED, error=str(exc)[:500])
    finally:
        db.close()


def create_task(
    db: Session,
    *,
    review_type: str,
    content: str | None,
    filename: str | None,
    file_bytes: bytes | None,
    created_by: str | None,
) -> ReviewTask:
    """创建审查任务：文本直接入库，文件落地到 uploads/reviews。"""
    if review_type not in (REVIEW_TYPE_CONTRACT, REVIEW_TYPE_REGULATION):
        raise BizError(message=f"未知的审查类型：{review_type}")
    if not content and not file_bytes:
        raise BizError(message="请提供待审查的文本内容或文件")

    task = ReviewTask(
        review_type=review_type,
        input_type="file" if file_bytes else "text",
        source_name=filename,
        status=REVIEW_STATUS_PENDING,
        created_by=created_by,
    )

    if file_bytes:
        reviews_dir = Path(settings.UPLOAD_DIR) / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename or "").suffix.lower() or ".txt"
        target = reviews_dir / f"{uuid.uuid4().hex}{suffix}"
        target.write_bytes(file_bytes)
        task.source_path = str(target)

    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> ReviewTask:
    task = db.get(ReviewTask, task_id)
    if task is None:
        raise NotFoundError("审查任务不存在")
    return task


def parse_result(task: ReviewTask) -> dict | None:
    if not task.result_json:
        return None
    try:
        return json.loads(task.result_json)
    except json.JSONDecodeError:
        return None


def list_tasks(
    db: Session, *, review_type: str | None = None, page: int = 1, page_size: int = 10
) -> tuple[list[ReviewTask], int]:
    stmt = select(ReviewTask)
    count_stmt = select(func.count()).select_from(ReviewTask)
    if review_type:
        stmt = stmt.where(ReviewTask.review_type == review_type)
        count_stmt = count_stmt.where(ReviewTask.review_type == review_type)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(ReviewTask.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def delete_task(db: Session, task: ReviewTask) -> None:
    if task.source_path:
        Path(task.source_path).unlink(missing_ok=True)
    db.delete(task)
    db.commit()
