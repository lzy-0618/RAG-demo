"""合同模板库路由（需求 ⑥）：导入、结构化、复核、预览、下载、删除、类型词表。

模板的生命周期：导入（pending）→ 识别（structuring → review）→ 人工复核确认（ready）→ 生成页可选。
识别结果不直接生效，必须复核——AI 识别必然有错，而合同出错代价高。
"""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.exceptions import BizError
from app.schemas.common import ok
from app.schemas.template import (
    CategoryCreate,
    TemplateDetailOut,
    TemplateField,
    TemplateFieldsRequest,
    TemplateOut,
    TemplateUpdate,
)
from app.services import docx_convert, template_scan
from app.services import template as template_service

router = APIRouter(prefix="/templates", tags=["合同模板库"])


def _field_out(item) -> list[TemplateField]:
    return [TemplateField(**field) for field in template_service.parse_fields(item)]


def _base(item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category,
        "file_name": item.file_name,
        "file_size": item.file_size or 0,
        "variables": template_service.parse_variables(item),
        "fields": _field_out(item),
        "description": item.description,
        "uploader": item.uploader,
        "structure_status": item.structure_status or "pending",
        "version": item.version or 1,
        "standardized": bool(item.standardized_path),
        "created_at": item.created_at.isoformat(sep=" ") if item.created_at else None,
        "updated_at": item.updated_at.isoformat(sep=" ") if item.updated_at else None,
    }


def _payload(item) -> dict:
    return TemplateOut(**_base(item)).model_dump()


def _detail_payload(item) -> dict:
    """复核页上下文：文档大纲 + 候选空位 + 识别过程留痕。"""
    outline = ""
    candidates: list[dict] = []
    try:
        scan = template_scan.scan_document(item.source_path or item.file_path)
        outline = scan.outline
        candidates = template_scan.candidates_for_ai(scan.candidates)
    except BizError:
        # 原始文件损坏时仍返回模板信息，复核页会提示只有 status/error 可用
        pass
    meta = template_service.parse_meta(item)
    return TemplateDetailOut(
        **_base(item),
        outline=outline,
        candidates=candidates,
        meta=meta,
        error=str(meta.get("error") or ""),
    ).model_dump()


# ===== 合同类型词表（必须声明在 /{template_id} 之前，否则会被当成路径参数）=====


@router.get("/categories")
async def list_categories(
    db: Session = Depends(get_db), current_user: str = Depends(get_current_user)
):
    """合同类型词表（受控，替代原先用户手打的自由文本）。"""
    return ok({"items": template_service.list_categories(db)})


@router.post("/categories")
async def create_category(
    request: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    item = template_service.create_category(db, request.name, request.sort_order)
    return ok({"id": item.id, "name": item.name, "sort_order": item.sort_order})


@router.post("/categories/seed")
async def seed_categories(
    db: Session = Depends(get_db), current_user: str = Depends(get_current_user)
):
    """把存量模板里手打的分类灌进词表（一次性迁移，可重复执行）。"""
    return ok({"created": template_service.seed_categories_from_templates(db)})


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    template_service.delete_category(db, category_id)
    return ok({"id": category_id})


# ===== 模板 =====


@router.get("")
async def list_templates(
    category: str | None = Query(None, description="按合同类型过滤"),
    status: str | None = Query(None, description="按结构化状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """模板列表（分页 + 类型/状态过滤），含字段 schema 与类型词表。"""
    items, total = template_service.list_templates(
        db, category=category, page=page, page_size=page_size
    )
    if status:
        items = [item for item in items if (item.structure_status or "pending") == status]
    return ok(
        {
            "items": [_payload(item) for item in items],
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
    category: str | None = Form(None, description="合同类型，来自类型词表"),
    description: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """导入模板：落地原始文件 → 落库（state=pending）。随后需调用 /structure 做结构化。"""
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


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """模板详情：供复核页使用（含文档大纲、候选空位、识别留痕）。"""
    item = template_service.get_template(db, template_id)
    return ok(_detail_payload(item))


@router.patch("/{template_id}")
async def update_template(
    template_id: int,
    request: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """修改模板元信息（名称/类型/说明）。"""
    item = template_service.get_template(db, template_id)
    item = template_service.update_template_meta(
        db,
        item,
        name=request.name,
        category=request.category,
        description=request.description,
    )
    return ok(_payload(item))


@router.post("/{template_id}/structure")
async def structure_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """识别待填字段：扫描 → AI（Dify 应用六）→ 回写标准化模板 → 自检。

    识别结果落到 review 状态，需人工在复核页确认后才启用。失败原因会写进模板留痕。
    """
    item = template_service.get_template(db, template_id)
    return ok(await template_service.structure_template(db, item, current_user))


@router.post("/{template_id}/fields")
async def save_template_fields(
    template_id: int,
    request: TemplateFieldsRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """保存复核后的字段定义：重新回写标准化模板（含自检），enable=true 时启用。"""
    item = template_service.get_template(db, template_id)
    result = template_service.save_fields(
        db,
        item,
        fields=[field.model_dump() for field in request.fields],
        contract_type=request.contract_type,
        enable=request.enable,
    )
    return ok(result)


@router.post("/{template_id}/reset")
async def reset_template_structure(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """回到待识别状态（想重跑识别时用）。"""
    item = template_service.get_template(db, template_id)
    template_service.reset_structure(db, item)
    return ok({"id": template_id, "structure_status": item.structure_status})


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


@router.get("/{template_id}/preview")
async def preview_template_meta(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """预览元信息（页数 + 每页尺寸）：{code, message, data:{dpi, page_count, pages}}。

    转换后会做中文字形自检，字形缺失直接报错，不会返回空白预览。
    """
    item = template_service.get_template(db, template_id)
    return ok(await docx_convert.preview_meta(item.file_path))


@router.get("/{template_id}/preview/{page_no}")
async def preview_template_page(
    template_id: int,
    page_no: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """预览单页图片（PNG）。

    由后端光栅化而非交给前端 pdf.js：pdf.js 渲染 LibreOffice 导出的中文 CID 子集时
    字形会错位，MuPDF 渲染同一份 PDF 正确。
    """
    item = template_service.get_template(db, template_id)
    png_path = await docx_convert.render_page(item.file_path, page_no)
    return FileResponse(png_path, media_type="image/png", content_disposition_type="inline")


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """删除模板（软删除：保留文件与记录，生成历史仍可读）。"""
    item = template_service.get_template(db, template_id)
    template_service.delete_template(db, item)
    return ok({"id": template_id})
