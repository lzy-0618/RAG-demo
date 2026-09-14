"""知识库业务逻辑：入库、状态同步、维护（需求 ①⑨）。

职责边界：
- 本地 Document 表保存元数据（文件路径、Dify 文档 ID、索引状态）；
- 解析与检索全部交给 Dify 知识库（不自建向量链路）；
- 长文档的文本预处理（扫描件/复杂法务文档）走 document_parser，属 Phase 2。

索引是异步的：创建文档后立即置 parsing，由 refresh/列表接口轮询 indexing-status 回写。
"""

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    DOC_STATUS_FAILED,
    DOC_STATUS_PARSING,
    DOC_STATUS_READY,
    DOC_STATUS_UPLOADED,
)
from app.core.exceptions import BizError, NotFoundError
from app.models.document import Document
from app.services.dify import dify_client

# 知识库标识 → (展示名, settings 中的 dataset_id 字段名)
DATASET_META: dict[str, tuple[str, str]] = {
    "law": ("法律法规库", "DATASET_ID_LAW"),
    "regulation": ("某钢规章制度库", "DATASET_ID_REGULATION"),
    "case": ("典型案例库", "DATASET_ID_CASE"),
    "rule": ("审核规则库", "DATASET_ID_RULE"),
    "expert": ("专家知识库", "DATASET_ID_EXPERT"),
}

# Dify indexing-status 返回的 indexing_status → 本地状态（未列出的中间态一律视为解析中）
_DIFY_STATUS_MAP = {
    "completed": DOC_STATUS_READY,
    "error": DOC_STATUS_FAILED,
}


def _map_indexing_status(value: str | None) -> str:
    return _DIFY_STATUS_MAP.get(str(value or ""), DOC_STATUS_PARSING)


def _dataset_id_of(dataset_key: str) -> str:
    return getattr(settings, DATASET_META[dataset_key][1], "") if dataset_key in DATASET_META else ""


def resolve_dataset(dataset_key: str) -> tuple[str, str]:
    """校验知识库标识并返回 (dataset_id, 展示名)。"""
    meta = DATASET_META.get(dataset_key)
    if meta is None:
        raise BizError(message=f"未知的知识库类别：{dataset_key}")
    name, setting_name = meta
    dataset_id = getattr(settings, setting_name, "")
    if not dataset_id:
        raise BizError(message=f"{name} 未配置 dataset_id，请检查后端 .env")
    return dataset_id, name


# dataset_id → doc_form 进程内缓存：doc_form 决定分段结构，创建文档时必须与库一致
_doc_form_cache: dict[str, str] = {}


async def _doc_form_of(dataset_id: str) -> str | None:
    """取知识库的 doc_form（如 hierarchical_model），创建文档时必须回传。

    Dify 校验请求的 doc_form 与库一致，否则返回 400；缓存避免每次上传都多一次查询。
    """
    if dataset_id in _doc_form_cache:
        return _doc_form_cache[dataset_id]
    detail = await dify_client.get_dataset(settings.DIFY_API_KEY, dataset_id)
    doc_form = detail.get("doc_form") or ""
    if doc_form:
        _doc_form_cache[dataset_id] = doc_form
    return doc_form or None


def list_datasets(db: Session) -> list[dict]:
    """列出 5 个业务知识库及其配置/本地文档数（供知识库维护页使用）。"""
    counts = dict(
        db.execute(
            select(Document.dataset_key, func.count()).group_by(Document.dataset_key)
        ).all()
    )
    items = []
    for key, (name, _) in DATASET_META.items():
        dataset_id = _dataset_id_of(key)
        items.append(
            {
                "key": key,
                "name": name,
                "dataset_id": dataset_id,
                "configured": bool(dataset_id),
                "document_count": counts.get(key, 0),
            }
        )
    return items


def _save_upload(filename: str, content: bytes) -> Path:
    """落地到 UPLOAD_DIR，文件名加 uuid 前缀避免重名覆盖。"""
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"{uuid.uuid4().hex}_{Path(filename).name}"
    target.write_bytes(content)
    return target


def _mark_failed(db: Session, doc: Document, exc: Exception) -> None:
    doc.status = DOC_STATUS_FAILED
    doc.error = str(exc)[:500]
    db.commit()
    db.refresh(doc)


def _absorb_duplicate(db: Session, doc: Document) -> Document:
    """合并「同名去重」产生的重复记录。

    Dify 对同一知识库内的同名文件/文档会去重复用（返回已存在的文档 ID，不新建）。
    此时本地若再插一条记录，就会出现多条记录指向同一个 Dify 文档；这里把新记录
    合并到已有记录上（即「同名重传 = 重新索引已有文档」的更新语义）。
    """
    if not doc.dify_document_id:
        return doc
    existing = (
        db.execute(
            select(Document).where(
                Document.dify_document_id == doc.dify_document_id, Document.id != doc.id
            )
        )
        .scalars()
        .first()
    )
    if existing is None:
        return doc

    existing.title = doc.title
    existing.doc_type = doc.doc_type
    existing.status = doc.status
    existing.dify_batch = doc.dify_batch
    existing.error = doc.error
    existing.uploader = doc.uploader or existing.uploader
    # 保留仍在磁盘上的文件，避免留下孤儿文件
    if doc.file_path:
        if existing.file_path and existing.file_path != doc.file_path and Path(existing.file_path).exists():
            Path(doc.file_path).unlink(missing_ok=True)
        else:
            existing.file_path = doc.file_path

    db.delete(doc)
    db.commit()
    db.refresh(existing)
    return existing


async def create_file_document(
    db: Session, *, dataset_key: str, filename: str, content: bytes, uploader: str | None
) -> Document:
    """文件入库（需求①）：落地本地 → Dify create_by_file → 记录 batch 等待索引。"""
    if not content:
        raise BizError(message="上传文件为空")
    limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > limit:
        raise BizError(message=f"文件超过 {settings.MAX_UPLOAD_SIZE_MB}MB 限制")
    dataset_id, _ = resolve_dataset(dataset_key)

    path = await asyncio.to_thread(_save_upload, filename, content)
    doc = Document(
        title=Path(filename).name,
        dataset_key=dataset_key,
        doc_type="file",
        file_path=str(path),
        status=DOC_STATUS_UPLOADED,
        uploader=uploader,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        doc_form = await _doc_form_of(dataset_id)
        created = await dify_client.create_document_by_file(
            settings.DIFY_API_KEY,
            dataset_id,
            str(path),
            Path(filename).name,
            doc_form=doc_form,
        )
    except Exception as exc:  # noqa: BLE001 - 需把上游错误落到文档状态供前端展示
        _mark_failed(db, doc, exc)
        raise BizError(message=f"入库失败：{exc}") from exc

    document = created.get("document") or {}
    doc.dify_document_id = document.get("id")
    doc.dify_batch = created.get("batch")
    doc.status = DOC_STATUS_PARSING
    db.commit()
    db.refresh(doc)
    return _absorb_duplicate(db, doc)


async def create_text_document(
    db: Session, *, dataset_key: str, title: str, text: str, uploader: str | None
) -> Document:
    """文本入库（审核规则、专家标注等）：Dify create_by_text。"""
    dataset_id, _ = resolve_dataset(dataset_key)

    doc = Document(
        title=title,
        dataset_key=dataset_key,
        doc_type="text",
        status=DOC_STATUS_UPLOADED,
        uploader=uploader,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    try:
        doc_form = await _doc_form_of(dataset_id)
        created = await dify_client.create_document_by_text(
            settings.DIFY_API_KEY, dataset_id, title, text, doc_form=doc_form
        )
    except Exception as exc:  # noqa: BLE001
        _mark_failed(db, doc, exc)
        raise BizError(message=f"文本入库失败：{exc}") from exc

    document = created.get("document") or {}
    doc.dify_document_id = document.get("id")
    doc.dify_batch = created.get("batch")
    doc.status = DOC_STATUS_PARSING
    db.commit()
    db.refresh(doc)
    return _absorb_duplicate(db, doc)


async def sync_status(db: Session, doc: Document) -> Document:
    """轮询 Dify 索引状态并回写（已 ready 的文档不再查询）。"""
    if not doc.dify_batch or doc.status == DOC_STATUS_READY:
        return doc
    dataset_id, _ = resolve_dataset(doc.dataset_key)
    result = await dify_client.indexing_status(
        settings.DIFY_API_KEY, dataset_id, doc.dify_batch
    )
    items = result.get("data") or []
    if not items:
        return doc

    statuses = {str(item.get("indexing_status", "")) for item in items}
    if "error" in statuses:
        doc.status = DOC_STATUS_FAILED
        doc.error = next(
            (str(item.get("error")) for item in items if item.get("error")), "索引失败"
        )[:500]
    elif statuses == {"completed"}:
        doc.status = DOC_STATUS_READY
        doc.error = None
    else:
        doc.status = DOC_STATUS_PARSING
    db.commit()
    db.refresh(doc)
    return doc


async def delete_document(db: Session, doc: Document) -> None:
    """从 Dify 与本地同时删除（Dify 删失败时保留本地记录，避免状态不一致）。"""
    if doc.dify_document_id:
        dataset_id, _ = resolve_dataset(doc.dataset_key)
        try:
            await dify_client.delete_document(
                settings.DIFY_API_KEY, dataset_id, doc.dify_document_id
            )
        except Exception as exc:  # noqa: BLE001
            raise BizError(message=f"删除 Dify 文档失败：{exc}") from exc
    if doc.file_path:
        Path(doc.file_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


def get_document(db: Session, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


async def sync_from_dify(db: Session, dataset_key: str) -> dict:
    """把 Dify 中已存在的文档补录到本地表。

    场景：早期直接在 Dify 控制台上传的文档本地没有记录，知识库维护页会显示为空。
    同步只补录缺失项（按 dify_document_id 去重），不修改已有记录。
    """
    dataset_id, name = resolve_dataset(dataset_key)
    created = 0
    page = 1

    while page <= 10:  # 每页 100，最多 1000 篇，避免异常情况下无限翻页
        result = await dify_client.list_documents(
            settings.DIFY_API_KEY, dataset_id, page=page, limit=100
        )
        items = result.get("data") or []
        if not items:
            break
        for item in items:
            dify_id = item.get("id")
            if not dify_id:
                continue
            exists = (
                db.execute(select(Document).where(Document.dify_document_id == dify_id))
                .scalars()
                .first()
            )
            if exists:
                continue
            data_source_type = str(item.get("data_source_type") or "")
            db.add(
                Document(
                    title=item.get("name") or "未命名文档",
                    dataset_key=dataset_key,
                    doc_type="file" if data_source_type.startswith("upload") else "text",
                    status=_map_indexing_status(item.get("indexing_status")),
                    dify_document_id=dify_id,
                    dify_batch=item.get("batch"),
                    uploader=None,
                )
            )
            created += 1
        if not result.get("has_more"):
            break
        page += 1

    db.commit()
    return {"dataset_key": dataset_key, "dataset_name": name, "created": created}


def list_documents(
    db: Session, *, dataset_key: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[Document], int]:
    """本地文档列表（按知识库过滤 + 分页）。"""
    conditions = []
    if dataset_key:
        if dataset_key not in DATASET_META:
            raise BizError(message=f"未知的知识库类别：{dataset_key}")
        conditions.append(Document.dataset_key == dataset_key)

    stmt = select(Document)
    count_stmt = select(func.count()).select_from(Document)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Document.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), total
