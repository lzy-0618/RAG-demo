"""知识库路由：文档上传/查询/删除（需求 ①⑨）。"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.deps import get_current_user
from app.services.dify import dify_client

router = APIRouter(prefix="/knowledge", tags=["知识库"])


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
):
    """上传文档到 Dify 知识库。"""
    content = await file.read()
    # TODO: 落地到 UPLOAD_DIR 后调用 dify_client.upload_document，并记录文档状态
    return {
        "code": 0,
        "message": "ok",
        "data": {"filename": file.filename, "size": len(content)},
    }


@router.get("/documents")
async def list_documents(current_user: str = Depends(get_current_user)):
    """查询知识库文档列表（占位）。"""
    return {"code": 0, "message": "ok", "data": []}
