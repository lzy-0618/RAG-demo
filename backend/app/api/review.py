"""合同审查路由：调用 Dify 审查工作流（需求 ②）。"""

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import get_current_user
from app.schemas.review import ReviewRequest
from app.services.dify import dify_client

router = APIRouter(prefix="/review", tags=["合同审查"])


@router.post("/contract")
async def review_contract(request: ReviewRequest, current_user: str = Depends(get_current_user)):
    """合同审查：检索 + 多步推理工作流，同步返回审查结果。"""
    api_key = settings.DIFY_REVIEW_APP_KEY or settings.DIFY_API_KEY
    result = await dify_client.run_workflow(
        api_key=api_key,
        inputs={"content": request.content, "review_type": request.review_type},
        user=current_user,
    )
    outputs = result.get("data", {}).get("outputs", {})
    return {"code": 0, "message": "ok", "data": outputs}
