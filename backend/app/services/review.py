"""审查任务编排：合同由 Dify 提取、切块和逐块审查；制度沿用后端切块。"""

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
from app.services import document_parser, docx_convert
from app.services.contract_review import validate_contract_report
from app.services.dify import dify_client

# 逐块调用的并发度：Dify 与上游模型都有速率限制，3 是速度与稳定性的折中
CHUNK_CONCURRENCY = 3
# 跨块合并时判定「同一风险」的条款文本相似度阈值
CLAUSE_SIMILARITY_THRESHOLD = 0.7
CONTRACT_RETRIEVAL_NODES = {"1789090408803", "1789091013980", "1789091060151"}
CONTRACT_LLM_NODE = "1789091095600"
# 与 dify/dsl/合同审查.yml 的 iter_review.parallel_nums 保持一致。
CONTRACT_PARALLEL_CHUNKS = 3


def _contract_progress(stage: str = "upload") -> dict:
    return {"stage": stage, "processed_chunks": 0, "active_chunks": []}


def _save_contract_progress(db: Session, task: ReviewTask, progress: dict) -> None:
    _update(db, task, result_json=json.dumps({"_progress": progress}, ensure_ascii=False))


def _iteration_chunk(data: dict) -> int | None:
    metadata = data.get("execution_metadata") or {}
    index = metadata.get("iteration_index")
    if index is None:
        index = data.get("iteration_index", (data.get("metadata") or {}).get("iterator_index"))
    if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
        return index + 1
    return None


def _apply_contract_event(
    progress: dict,
    event: dict,
    done_indices: set[int],
    retrieval_done: dict[int, set[str]],
    queued_indices: list[int],
) -> bool:
    """将 Dify 节点事件映射为审查进度；并行迭代按块号独立更新。"""
    kind = event.get("event")
    data = event.get("data") or {}
    node_id = str(data.get("node_id") or "")
    active = {item["index"]: item["phase"] for item in progress["active_chunks"]}
    changed = False

    if kind == "node_finished" and node_id == "split_contract":
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
                if len(active) < CONTRACT_PARALLEL_CHUNKS:
                    active[index] = "retrieval"
                    changed = True
    elif kind == "node_started" and node_id in CONTRACT_RETRIEVAL_NODES | {CONTRACT_LLM_NODE}:
        index = _iteration_chunk(data)
        if index is not None and index not in done_indices:
            progress["stage"] = "review"
            phase = "generation" if node_id == CONTRACT_LLM_NODE else "retrieval"
            # 并行检索节点可能交错；同一块进入生成后不退回检索。
            if active.get(index) != "generation" or phase == "generation":
                active[index] = phase
            changed = True
    elif kind == "node_finished" and node_id in CONTRACT_RETRIEVAL_NODES:
        index = _iteration_chunk(data)
        if index is not None and index not in done_indices:
            completed = retrieval_done.setdefault(index, set())
            completed.add(node_id)
            active[index] = "generation" if completed == CONTRACT_RETRIEVAL_NODES else "retrieval"
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
                        "case_analysis": str(risk.get("case_analysis") or ""),
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
            if not target.get("case_analysis") and risk.get("case_analysis"):
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
    """审查制度文本，供「规章制度生成后的自动审查」使用。
    on_start(total) 在解析完切块后立即回调（前端可提前显示总块数），
    on_progress(completed, total, failed) 用于汇报进度（同步回调）。
    """
    if review_type != REVIEW_TYPE_REGULATION:
        raise ValueError("合同文本须通过 Dify 文件工作流审查")
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
    failed_details = [
        {"chunk_index": item["chunk_index"], "location": item.get("location") or "",
         "error": item.get("error") or "审查失败"}
        for item in results if item["failed"]
    ]
    return {
        "is_compliant": not risks and failed == 0,
        "summary": build_summary(risks, len(parsed.chunks), failed),
        "total_chunks": len(parsed.chunks),
        "failed_chunks": failed,
        "failed_details": failed_details,
        "risks": risks,
    }


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


async def _review_chunk(
    semaphore: asyncio.Semaphore, api_key: str, chunk: document_parser.TextChunk,
    user: str,
) -> dict:
    """审查一个制度文本块；失败时不中断其余块。"""
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


def _contract_iteration_results(outputs: dict) -> list[dict]:
    """用 Dify 原样返回的文本块校验同一次迭代产生的报告。"""
    chunks, reports = outputs.get("chunks"), outputs.get("results")
    if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
        raise ValueError("Dify 未返回合同文本块数组")
    if not isinstance(reports, list) or len(reports) != len(chunks):
        raise ValueError("Dify 审查结果数量与文本块数量不一致")
    results = []
    for index, (chunk, report) in enumerate(zip(chunks, reports), start=1):
        item = {"chunk_index": index, "location": f"第 {index} 块", "risks": []}
        try:
            payload = json.loads(report) if isinstance(report, str) else report
            if not isinstance(payload, dict) or payload.get("chunk_text") != chunk:
                raise ValueError("审查结果与当前文本块不匹配")
            item["risks"] = validate_contract_report(payload, chunk)
            item["failed"] = False
        except (ValueError, TypeError) as exc:
            item.update(failed=True, error=str(exc)[:300])
        results.append(item)
    return results


async def _review_contract_file(file_path: str, user: str, db: Session, task: ReviewTask) -> dict:
    """将文件交给 Dify；提取、切块和逐块审查都在同一工作流内完成。"""
    api_key = review_app_key(REVIEW_TYPE_CONTRACT)
    uploaded = await dify_client.upload_file(api_key, file_path, Path(file_path).name, user)
    file_id = uploaded.get("id")
    if not file_id:
        raise ValueError("Dify 文件上传未返回 id")
    progress = _contract_progress("parse")
    _save_contract_progress(db, task, progress)
    inputs = {"input_file": {
        "type": "document", "transfer_method": "local_file", "upload_file_id": file_id,
    }}
    finished = None
    done_indices: set[int] = set()
    retrieval_done: dict[int, set[str]] = {}
    queued_indices: list[int] = []
    async for event in dify_client.run_workflow_stream(api_key, inputs, user, long_running=True):
        if event.get("event") == "error":
            raise ValueError(str(event.get("message") or "Dify 合同审查失败"))
        if _apply_contract_event(progress, event, done_indices, retrieval_done, queued_indices):
            _update(
                db, task, result_json=json.dumps({"_progress": progress}, ensure_ascii=False),
                total_chunks=progress.get("total_chunks", task.total_chunks),
            )
        if event.get("event") == "workflow_finished":
            finished = event.get("data") or {}
    if finished is None:
        raise ValueError("Dify 合同审查未返回完成事件")
    if finished.get("status") != "succeeded":
        raise ValueError(str(finished.get("error") or "Dify 合同审查失败"))
    results = _contract_iteration_results(finished.get("outputs") or {})
    failed = sum(bool(item["failed"]) for item in results)
    risks = merge_risks(results, REVIEW_TYPE_CONTRACT)
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

        if task.review_type == REVIEW_TYPE_CONTRACT:
            result = await _review_contract_file(
                task.source_path or "", task.created_by or "review", db, task
            )
            _update(
                db, task, status=REVIEW_STATUS_COMPLETED,
                total_chunks=result["total_chunks"],
                completed_chunks=result["total_chunks"] - result["failed_chunks"],
                failed_chunks=result["failed_chunks"],
                is_compliant=result["is_compliant"], summary=result["summary"],
                result_json=json.dumps(result, ensure_ascii=False),
            )
            return

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
            asyncio.create_task(_review_chunk(
                semaphore, api_key, chunk, task.created_by or "review"
            ))
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
            "failed_details": [
                {"chunk_index": item["chunk_index"], "location": item.get("location") or "",
                 "error": item.get("error") or "审查失败"}
                for item in chunk_results if item["failed"]
            ],
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


async def create_task(
    db: Session,
    *,
    review_type: str,
    content: str | None,
    filename: str | None,
    file_bytes: bytes | None,
    created_by: str | None,
) -> ReviewTask:
    """创建审查任务：文本直接入库，文件落地到 uploads/reviews（legacy .doc 先归一化为 .docx）。

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
    if review_type == REVIEW_TYPE_CONTRACT:
        task.result_json = json.dumps({"_progress": _contract_progress()}, ensure_ascii=False)

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
    if task.review_type != REVIEW_TYPE_CONTRACT:
        return None
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
