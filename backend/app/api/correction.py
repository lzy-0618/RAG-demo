"""内容纠错路由（需求 ⑤）：专家对 AI 回答的就地标注。

所有接口均受 require_expert 保护——普通用户（user 角色）返回 403。
提交即写入专家知识库（无审核），失败可重试。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_expert
from app.schemas.common import ok
from app.schemas.correction import CorrectionCreate, CorrectionOut
from app.services import correction as correction_service

router = APIRouter(prefix="/corrections", tags=["内容纠错"])


@router.post("")
async def create_correction(
    request: CorrectionCreate,
    db: Session = Depends(get_db),
    principal=Depends(require_expert),
):
    """提交专家标注：写入专家知识库并落库（write_status 为 failed 时可重试）。"""
    item = await correction_service.create_correction(
        db,
        source_content=request.source_content,
        corrected_content=request.corrected_content,
        question=request.question,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        expert=principal.username,
    )
    return ok(CorrectionOut.from_model(item).model_dump())


@router.get("")
async def list_corrections(
    expert: str | None = Query(None, description="按专家用户名过滤"),
    message_id: str | None = Query(None, description="按消息 ID 过滤（回看某条回答的标注）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal=Depends(require_expert),
):
    """标注记录列表（默认全部，专家可只看自己的）。"""
    items, total = correction_service.list_corrections(
        db, expert=expert, message_id=message_id, page=page, page_size=page_size
    )
    return ok(
        {
            "items": [CorrectionOut.from_model(i).model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/{correction_id}/retry")
async def retry_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal=Depends(require_expert),
):
    """写入知识库失败后重试。"""
    item = correction_service.get_correction(db, correction_id)
    item = await correction_service.retry_write(db, item)
    return ok(CorrectionOut.from_model(item).model_dump())


@router.delete("/{correction_id}")
async def delete_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal=Depends(require_expert),
):
    """删除标注（连同其在专家知识库中的文档一起删除）。"""
    item = correction_service.get_correction(db, correction_id)
    await correction_service.delete_correction(db, item)
    return ok({"id": correction_id})
