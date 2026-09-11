"""生成路由：合同/规章制度 Word 生成（需求 ⑦⑧）。"""

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.deps import get_current_user
from app.schemas.generate import GenerateRequest
from app.services.dify import dify_client
from app.services.word_generator import render_template

router = APIRouter(prefix="/generate", tags=["生成"])


@router.post("")
async def generate(request: GenerateRequest, current_user: str = Depends(get_current_user)):
    """大纲生成 + Word 生成：先走 Dify 生成内容，再填充模板。"""
    api_key = settings.DIFY_GENERATE_APP_KEY or settings.DIFY_API_KEY
    result = await dify_client.run_workflow(
        api_key=api_key,
        inputs={"outline": request.outline, "variables": request.variables},
        user=current_user,
    )
    content = result.get("data", {}).get("outputs", {})
    # TODO: 将 content 与模板结合，用 render_template 生成 .docx 并返回下载链接
    return {"code": 0, "message": "ok", "data": content}
