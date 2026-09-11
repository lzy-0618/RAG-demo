"""合同模板库路由：模板文件导入/管理（需求 ⑥）。"""

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user

router = APIRouter(prefix="/templates", tags=["合同模板库"])


@router.get("")
async def list_templates(current_user: str = Depends(get_current_user)):
    return {"code": 0, "message": "ok", "data": []}


@router.post("")
async def create_template(current_user: str = Depends(get_current_user)):
    # TODO: 接收模板文件并入库
    return {"code": 0, "message": "ok", "data": None}
