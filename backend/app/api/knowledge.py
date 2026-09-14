"""知识库路由：文档上传入库、文本入库、列表、状态刷新、删除（需求 ①⑨）。

路由层只做参数校验与依赖注入，业务逻辑在 services/knowledge.py。
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.schemas.common import ok
from app.schemas.knowledge import DocumentOut, TextDocumentCreate
from app.services import knowledge as knowledge_service

router = APIRouter(prefix="/knowledge", tags=["知识库"])


@router.get("/datasets")
async def list_datasets(
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """列出 5 个业务知识库（含 dataset_id 配置情况与本地文档数）。"""
    return ok(knowledge_service.list_datasets(db))


@router.post("/datasets/{dataset_key}/sync")
async def sync_dataset(
    dataset_key: str,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """把 Dify 中已有但本地缺失的文档补录到本地表（知识库维护：历史文档可见）。"""
    return ok(await knowledge_service.sync_from_dify(db, dataset_key))


@router.post("/upload")
async def upload_document(
    dataset_key: str = Form(..., description="知识库标识：law/regulation/case/rule/expert"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """文件入库（需求①）：落地 → Dify create_by_file → 返回文档状态（异步索引中）。"""
    content = await file.read()
    doc = await knowledge_service.create_file_document(
        db,
        dataset_key=dataset_key,
        filename=file.filename or "未命名文件",
        content=content,
        uploader=current_user,
    )
    return ok(DocumentOut.from_model(doc))


@router.post("/text")
async def create_text_document(
    request: TextDocumentCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """文本入库：审核规则、专家标注等以文本为主的知识库（需求⑨）。"""
    doc = await knowledge_service.create_text_document(
        db,
        dataset_key=request.dataset_key,
        title=request.title,
        text=request.text,
        uploader=current_user,
    )
    return ok(DocumentOut.from_model(doc))


@router.get("/documents")
async def list_documents(
    dataset_key: str | None = Query(None, description="按知识库标识过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """本地文档列表（分页 + 按知识库过滤），前端据此渲染状态流转。"""
    docs, total = knowledge_service.list_documents(
        db, dataset_key=dataset_key, page=page, page_size=page_size
    )
    return ok(
        {
            "items": [DocumentOut.from_model(d).model_dump() for d in docs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/documents/{document_id}/refresh")
async def refresh_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """刷新单个文档的索引状态（轮询 Dify indexing-status）。"""
    doc = knowledge_service.get_document(db, document_id)
    doc = await knowledge_service.sync_status(db, doc)
    return ok(DocumentOut.from_model(doc))


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除文档：Dify 与本地记录同步删除（需求⑨）。"""
    doc = knowledge_service.get_document(db, document_id)
    await knowledge_service.delete_document(db, doc)
    return ok({"id": document_id})
