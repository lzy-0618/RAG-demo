"""合同模板库路由（需求 ⑥）：模板导入、列表、下载、删除。

模板为含 `{{ 变量 }}` 的 .docx；导入时解析占位变量，供需求⑦生成时动态渲染表单。
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.schemas.common import ok
from app.schemas.template import TemplateOut, TemplateUpdate
from app.services import template as template_service

router = APIRouter(prefix="/templates", tags=["合同模板库"])


def _payload(item) -> dict:
    return TemplateOut.from_model(item, template_service.parse_variables(item)).model_dump()


@router.get("")
async def list_templates(
    category: str | None = Query(None, description="按合同类型过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """模板列表（分页 + 分类过滤），含解析出的占位变量。"""
    items, total = template_service.list_templates(
        db, category=category, page=page, page_size=page_size
    )
    return ok(
        {
            "items": [_payload(i) for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "categories": template_service.list_categories(db),
        }
    )


@router.post("")
async def create_template(
    file: UploadFile = File(..., description=".docx 模板文件"),
    name: str | None = Form(None, description="模板名称，默认取文件名"),
    category: str | None = Form(None, description="合同类型，如 采购/销售/服务"),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """导入模板：落地 templates/ → 解析占位变量 → 落库。"""
    content = await file.read()
    item = await template_service.create_template(
        db,
        filename=file.filename or "template.docx",
        content=content,
        name=name,
        category=category,
        description=description,
        uploader=current_user,
    )
    return ok(_payload(item))


@router.patch("/{template_id}")
async def update_template(
    template_id: int,
    request: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """修改模板元信息（名称/分类/说明）。"""
    item = template_service.get_template(db, template_id)
    if request.name is not None:
        item.name = request.name
    if request.category is not None:
        item.category = request.category or None
    if request.description is not None:
        item.description = request.description
    db.commit()
    db.refresh(item)
    return ok(_payload(item))


@router.get("/{template_id}/download")
async def download_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """下载模板原文件。"""
    item = template_service.get_template(db, template_id)
    return FileResponse(
        item.file_path,
        filename=item.file_name or f"{item.name}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除模板（同时移除模板文件）。"""
    item = template_service.get_template(db, template_id)
    template_service.delete_template(db, item)
    return ok({"id": template_id})
