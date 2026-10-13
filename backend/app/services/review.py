"""审查任务编排：合同与制度均由 Dify 提取、切块和逐块审查。"""

import tempfile
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
from app.services import docx_convert
from app.services.contract_review import validate_contract_report
from app.services.dify import dify_client

# 跨块合并时判定「同一风险」的条款文本相似度阈值
CLAUSE_SIMILARITY_THRESHOLD = 0.7
REGULATION_RETRIEVAL_NODES = {"1789090408803", "1789091013980"}
CONTRACT_RETRIEVAL_NODES = {"1789090408803", "1789091013980", "1789091060151"}
REVIEW_LLM_NODE = "1789091095600"
# 与 dify/dsl/合同审查.yml 的 iter_review.parallel_nums 保持一致。
REVIEW_PARALLEL_CHUNKS = 3


def _review_progress(stage: str = "upload") -> dict:
    return {"stage": stage, "processed_chunks": 0, "active_chunks": []}


def _iteration_chunk(data: dict) -> int | None:
    metadata = data.get("execution_metadata") or {}
    index = metadata.get("iteration_index")
    if index is None:
        index = data.get("iteration_index", (data.get("metadata") or {}).get("iterator_index"))
    if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
        return index + 1
    return None


def _apply_review_event(
    progress: dict,
    event: dict,
    done_indices: set[int],
    retrieval_done: dict[int, set[str]],
    queued_indices: list[int],
    review_type: str = REVIEW_TYPE_CONTRACT,
) -> bool:
    """将 Dify 节点事件映射为审查进度；并行迭代按块号独立更新。"""
    retrieval_nodes = (REGULATION_RETRIEVAL_NODES if review_type == REVIEW_TYPE_REGULATION
                       else CONTRACT_RETRIEVAL_NODES)
    kind = event.get("event")
    data = event.get("data") or {}
    node_id = str(data.get("node_id") or "")
    active = {item["index"]: item["phase"] for item in progress["active_chunks"]}
    changed = False

    if kind == "node_finished" and node_id in {"split_contract", "split_regulation"}:
        chunks = (data.get("outputs") or {}).get("chunks")
        if isinstance(chunks, list):
            progress["total_chunks"] = len(chunks)
            changed = True
    elif kind == "iteration_started" and node_id == "iter_review":
        progress["stage"] = "review"
        length = (data.get("metadata") or {}).get("iterator_length")
        if isinstance(length, int) and length >= 0:
            progress["total_chunks"] = length
        changed = True
    elif kind == "iteration_next" and node_id == "iter_review":
        raw_index = data.get("index")
        if isinstance(raw_index, int) and not isinstance(raw_index, bool) and raw_index >= 0:
            index = raw_index + 1
            if index not in queued_indices and index not in done_indices:
                queued_indices.append(index)
                if len(active) < REVIEW_PARALLEL_CHUNKS:
                    active[index] = "retrieval"
                    changed = True
    elif kind == "node_started" and node_id in retrieval_nodes | {REVIEW_LLM_NODE}:
        index = _iteration_chunk(data)
        if index is not None and index not in done_indices:
            progress["stage"] = "review"
            phase = "generation" if node_id == REVIEW_LLM_NODE else "retrieval"
            # 并行检索节点可能交错；同一块进入生成后不退回检索。
            if active.get(index) != "generation" or phase == "generation":
                active[index] = phase
            changed = True
    elif kind == "node_finished" and node_id in retrieval_nodes:
        index = _iteration_chunk(data)
        if index is not None and index not in done_indices:
            completed = retrieval_done.setdefault(index, set())
            completed.add(node_id)
            active[index] = "generation" if completed == retrieval_nodes else "retrieval"
            changed = True
    elif kind == "node_finished":
        if node_id == "pack_review":
            index = _iteration_chunk(data)
            if index is not None and index not in done_indices:
                done_indices.add(index)
                active.pop(index, None)
                progress["processed_chunks"] = len(done_indices)
                for waiting in queued_indices:
                    if waiting not in done_indices and waiting not in active:
                        active[waiting] = "retrieval"
                        break
                changed = True
    elif kind == "iteration_completed" and node_id == "iter_review":
        active.clear()
        changed = True

    if changed:
        progress["active_chunks"] = [
            {"index": index, "phase": phase} for index, phase in sorted(active.items())
        ]
    return changed


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
                        "analysis": str(risk.get("analysis") or ""),
                        "citations": list(risk.get("citations") or []),
                        "case_analysis": str(risk.get("case_analysis") or "") if review_type == REVIEW_TYPE_CONTRACT else "",
                        "needs_review": bool(risk.get("needs_review")),
                        "validation_notes": list(risk.get("validation_notes") or []),
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
            if len(str(risk.get("analysis") or "")) > len(target.get("analysis") or ""):
                target["analysis"] = str(risk["analysis"])
            if review_type == REVIEW_TYPE_CONTRACT and not target.get("case_analysis") and risk.get("case_analysis"):
                target["case_analysis"] = str(risk["case_analysis"])
            target["needs_review"] = bool(target.get("needs_review") or risk.get("needs_review"))
            for note in risk.get("validation_notes") or []:
                if note not in target.setdefault("validation_notes", []):
                    target["validation_notes"].append(note)
            seen_citations = {
                (c.get("document_name"), c.get("section"), c.get("url"))
                for c in target.get("citations") or []
            }
            for citation in risk.get("citations") or []:
                key = (citation.get("document_name"), citation.get("section"), citation.get("url"))
                if key not in seen_citations:
                    target.setdefault("citations", []).append(citation)
                    seen_citations.add(key)
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
    """将制度正文作为临时文件交给 Dify，复用于生成后的自动审查。"""
    if review_type != REVIEW_TYPE_REGULATION:
        raise ValueError("合同文本须通过 Dify 文件工作流审查")
    if not text.strip():
        raise ValueError("制度正文为空，无法审查")
    started = False

    def on_event(progress: dict) -> None:
        nonlocal started
        total = progress.get("total_chunks")
        if total is not None:
            if not started:
                if on_start:
                    on_start(total)
                started = True
            if on_progress:
                on_progress(progress["processed_chunks"], total, 0)

    with tempfile.TemporaryDirectory(prefix="regulation-review-") as directory:
        path = Path(directory) / "制度正文.txt"
        path.write_text(text, encoding="utf-8")
        result = await _review_file(str(path), review_type, user, on_event)
    if not started and on_start:
        on_start(result["total_chunks"])
    if on_progress:
        on_progress(result["total_chunks"] - result["failed_chunks"],
                    result["total_chunks"], result["failed_chunks"])
    return result


def build_summary(risks: list[dict], total_chunks: int, failed_chunks: int) -> str:
    """生成整体审查结论（代码模板生成，不额外调 LLM）。"""
    if failed_chunks == total_chunks and total_chunks:
        return f"共 {total_chunks} 个文本块均审查失败，未获得可用的审查结论，建议人工复核。"
    if not risks:
        if failed_chunks:
            text = (f"共 {total_chunks} 个文本块，成功审查 {total_chunks - failed_chunks} 个；"
                    "在成功审查的文本块中未发现风险。")
        else:
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


def _update(db: Session, task: ReviewTask, **fields) -> None:
    for key, value in fields.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)


def _iteration_results(outputs: dict, review_type: str = REVIEW_TYPE_CONTRACT) -> list[dict]:
    """用 Dify 原样返回的文本块校验同一次迭代产生的报告。"""
    chunks, reports = outputs.get("chunks"), outputs.get("results")
    if not isinstance(chunks, list) or not chunks or not all(isinstance(chunk, str) and chunk.strip() for chunk in chunks):
        raise ValueError("Dify 未返回有效的待审查文本块数组")
    if not isinstance(reports, list) or len(reports) != len(chunks):
        raise ValueError("Dify 审查结果数量与文本块数量不一致")
    results = []
    for index, (chunk, report) in enumerate(zip(chunks, reports), start=1):
        item = {"chunk_index": index, "location": f"第 {index} 块", "risks": []}
        try:
            payload = json.loads(report) if isinstance(report, str) else report
            if not isinstance(payload, dict) or payload.get("chunk_text") != chunk:
                raise ValueError("审查结果与当前文本块不匹配")
            item["risks"] = validate_contract_report(
                payload, chunk, include_cases=review_type == REVIEW_TYPE_CONTRACT
            )
            item["failed"] = False
        except (ValueError, TypeError) as exc:
            item.update(failed=True, error=str(exc)[:300])
        results.append(item)
    return results


async def _review_file(
    file_path: str, review_type: str, user: str, on_event=None
) -> dict:
    """将文件交给 Dify；提取、切块和逐块审查都在同一工作流内完成。"""
    api_key = review_app_key(review_type)
    uploaded = await dify_client.upload_file(api_key, file_path, Path(file_path).name, user)
    file_id = uploaded.get("id")
    if not file_id:
        raise ValueError("Dify 文件上传未返回 id")
    progress = _review_progress("parse")
    if on_event:
        on_event(progress)
    inputs = {"input_file": {
        "type": "document", "transfer_method": "local_file", "upload_file_id": file_id,
    }}
    finished = None
    done_indices: set[int] = set()
    retrieval_done: dict[int, set[str]] = {}
    queued_indices: list[int] = []
    async for event in dify_client.run_workflow_stream(api_key, inputs, user, long_running=True):
        if event.get("event") == "error":
            raise ValueError(str(event.get("message") or "Dify 审查失败"))
        if _apply_review_event(progress, event, done_indices, retrieval_done, queued_indices, review_type):
            if on_event:
                on_event(progress)
        if event.get("event") == "workflow_finished":
            finished = event.get("data") or {}
    if finished is None:
        raise ValueError("Dify 审查未返回完成事件")
    if finished.get("status") != "succeeded":
        raise ValueError(str(finished.get("error") or "Dify 审查失败"))
    results = _iteration_results(finished.get("outputs") or {}, review_type)
    failed = sum(bool(item["failed"]) for item in results)
    risks = merge_risks(results, review_type)
    return {
        "is_compliant": not risks and failed == 0,
        "summary": build_summary(risks, len(results), failed),
        "total_chunks": len(results),
        "failed_chunks": failed,
        "failed_details": [
            {"chunk_index": item["chunk_index"], "location": item["location"],
             "error": item.get("error") or "审查失败"}
            for item in results if item["failed"]
        ],
        "risks": risks,
    }


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

        def on_event(progress: dict) -> None:
            _update(
                db, task, result_json=json.dumps({"_progress": progress}, ensure_ascii=False),
                total_chunks=progress.get("total_chunks", task.total_chunks),
                completed_chunks=progress["processed_chunks"],
            )

        if source_text is not None and not task.source_path:
            reviews_dir = Path(settings.UPLOAD_DIR) / "reviews"
            reviews_dir.mkdir(parents=True, exist_ok=True)
            path = reviews_dir / f"{uuid.uuid4().hex}.txt"
            path.write_text(source_text, encoding="utf-8")
            _update(db, task, source_path=str(path))
        result = await _review_file(
            task.source_path or "", task.review_type, task.created_by or "review", on_event
        )
        _update(
            db, task, status=REVIEW_STATUS_COMPLETED,
            total_chunks=result["total_chunks"],
            completed_chunks=result["total_chunks"] - result["failed_chunks"],
            failed_chunks=result["failed_chunks"],
            is_compliant=result["is_compliant"], summary=result["summary"],
            result_json=json.dumps(result, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务异常必须落库，否则任务会永远停在 running
        task = db.get(ReviewTask, task_id)
        if task is not None:
            _update(db, task, status=REVIEW_STATUS_FAILED, error=str(exc)[:500])
    finally:
        db.close()


async def create_task(
    db: Session,
    *,
    review_type: str,
    content: str | None,
    filename: str | None,
    file_bytes: bytes | None,
    created_by: str | None,
) -> ReviewTask:
    """创建审查任务：文本在后台写为 TXT，文件落地到 uploads/reviews（legacy .doc 先归一化为 .docx）。

    归一化放在这里而不是解析处：.doc 是二进制老格式，解析器只认 OOXML，
    在入口转一次，后台审查与后续任何消费者都只需处理一种格式。
    """
    if review_type not in (REVIEW_TYPE_CONTRACT, REVIEW_TYPE_REGULATION):
        raise BizError(message=f"未知的审查类型：{review_type}")
    if review_type == REVIEW_TYPE_CONTRACT and content is not None:
        raise BizError(message="合同审查仅支持文件上传")
    if not content and not file_bytes:
        raise BizError(message="请提供待审查文件" if review_type == REVIEW_TYPE_CONTRACT else "请提供待审查的文本内容或文件")

    task = ReviewTask(
        review_type=review_type,
        input_type="file" if file_bytes else "text",
        source_name=filename,
        status=REVIEW_STATUS_PENDING,
        created_by=created_by,
    )
    task.result_json = json.dumps({"_progress": _review_progress()}, ensure_ascii=False)

    if file_bytes:
        reviews_dir = Path(settings.UPLOAD_DIR) / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename or "").suffix.lower() or ".txt"
        original = reviews_dir / f"{uuid.uuid4().hex}{suffix}"
        original.write_bytes(file_bytes)
        target = original
        if docx_convert.is_legacy_doc(original):
            try:
                target = await docx_convert.convert_legacy_doc(original, reviews_dir)
            finally:
                # 原始 .doc 不再被 task.source_path 引用，留着就是删除任务时清不掉的孤儿
                original.unlink(missing_ok=True)
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
        result = json.loads(task.result_json)
        if isinstance(result, dict) and "_progress" in result:
            return None
        if (isinstance(result, dict) and result.get("total_chunks")
                and result.get("failed_chunks") == result.get("total_chunks")
                and not result.get("risks")):
            result["summary"] = build_summary([], result["total_chunks"], result["failed_chunks"])
        return result
    except json.JSONDecodeError:
        return None


def get_progress(task: ReviewTask) -> dict | None:
    if task.status == REVIEW_STATUS_COMPLETED:
        return {"stage": "done", "processed_chunks": task.total_chunks, "active_chunks": []}
    try:
        value = json.loads(task.result_json or "{}")
    except json.JSONDecodeError:
        return None
    return value.get("_progress") if isinstance(value, dict) else None


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
