"""生成路由：合同生成（需求⑦）与规章制度生成（需求⑧）。

- 合同生成：docxtpl 模板填充，**确定性链路**，不依赖 Dify；生成记录落库并按归属校验下载；
- 规章制度生成：调「规章制度生成」Dify 工作流（大纲 / 全文），全文生成后自动做合规审查，
  不合规时带冲突清单与上一版全文重新生成，最多 3 轮（循环在后端编排）。
"""

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, get_principal
from app.core.deps import Principal
from app.core.config import settings
from app.core.exceptions import BizError, ForbiddenError, NotFoundError
from app.models.generation import ContractGeneration
from app.models.template import STRUCTURE_READY
from app.schemas.common import ok
from app.schemas.generate import RegulationDocumentRequest, RegulationOutlineRequest
from app.schemas.template import ContractGenerateOut, ContractGenerateRequest, ContractRecordOut
from app.services import generation as generation_service
from app.services import template as template_service
from app.services import word_generator

router = APIRouter(prefix="/generate", tags=["生成"])

_MEDIA_TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MEDIA_TYPE_PDF = "application/pdf"


def _generation_payload(task) -> dict:
    """生成任务出参：进度 + 大纲/章节 + 审查结果 + 下载地址。"""
    doc_url = f"/api/v1/generate/files/{task.doc_name}" if task.doc_name else None
    return {
        "id": task.id,
        "status": task.status,
        "phase": task.phase,
        "round": task.round,
        "max_rounds": task.max_rounds,
        "review_round": task.review_round,
        "total_chunks": task.total_chunks,
        "completed_chunks": task.completed_chunks,
        "failed_chunks": task.failed_chunks,
        "is_compliant": task.is_compliant,
        "summary": task.summary,
        "requirement": task.requirement,
        "outline": task.outline,
        "sections": generation_service.parse_sections(task),
        "review": generation_service.parse_review(task),
        "doc_name": task.doc_name,
        "download_url": doc_url,
        "error": task.error,
        "created_at": task.created_at.isoformat(sep=" ") if task.created_at else None,
    }


def _record_payload(record: ContractGeneration) -> dict:
    return ContractRecordOut(
        id=record.id,
        template_id=record.template_id,
        template_name=record.template_name,
        file_name=record.file_name,
        file_size=record.file_size or 0,
        missing_variables=_loads(record.missing_variables_json, []),
        values=_loads(record.values_json, {}),
        created_by=record.created_by,
        created_at=record.created_at.isoformat(sep=" ") if record.created_at else None,
    ).model_dump()


def _loads(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _get_owned_record(db: Session, record_id: int, principal: Principal) -> ContractGeneration:
    """取生成记录并校验归属：只有本人（或专家）能访问产物。"""
    record = db.get(ContractGeneration, record_id)
    if record is None:
        raise NotFoundError("生成记录不存在")
    if record.created_by != principal.username and not principal.is_expert:
        raise ForbiddenError("只能访问自己生成的合同")
    return record


@router.post("/contract")
async def generate_contract(
    request: ContractGenerateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """合同生成（需求⑦）：按模板填充字段，落库并返回带归属校验的下载地址。"""
    item = template_service.get_template(db, request.template_id)
    if (item.structure_status or "") != STRUCTURE_READY:
        raise BizError(
            message=f"模板「{item.name}」尚未完成字段确认（当前状态：{item.structure_status}），"
            "请先到合同模板库完成结构化与复核"
        )

    fields = {field["key"]: field for field in template_service.parse_fields(item)}
    missing_required = [
        fields[key]["label"]
        for key in template_service.missing_required(item, request.variables)
        if key in fields
    ]
    if missing_required:
        raise BizError(message="以下必填项未填写：" + "、".join(missing_required))

    output_path, file_name, missing = template_service.render_contract(
        db, item, request.variables
    )
    record = ContractGeneration(
        template_id=item.id,
        template_name=item.name,
        template_version=item.version or 1,
        values_json=json.dumps(request.variables, ensure_ascii=False),
        file_name=file_name,
        file_size=Path(output_path).stat().st_size,
        missing_variables_json=json.dumps(missing, ensure_ascii=False),
        created_by=principal.username,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return ok(
        ContractGenerateOut(
            record_id=record.id,
            template_id=item.id,
            template_name=item.name,
            file_name=file_name,
            download_url=f"/api/v1/generate/contract/records/{record.id}/download",
            missing_variables=missing,
        ).model_dump()
    )


@router.get("/contract/records")
async def list_contract_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    mine_only: bool = Query(True, description="仅看自己生成的（专家可关闭以查看全部）"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """合同生成历史。普通用户只能看自己的记录。"""
    stmt = select(ContractGeneration)
    count_stmt = select(func.count()).select_from(ContractGeneration)
    if mine_only or not principal.is_expert:
        stmt = stmt.where(ContractGeneration.created_by == principal.username)
        count_stmt = count_stmt.where(ContractGeneration.created_by == principal.username)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(ContractGeneration.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return ok(
        {
            "items": [_record_payload(record) for record in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/contract/records/{record_id}/download")
async def download_contract_record(
    record_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """下载合同产物（按记录 ID，校验归属；不再是裸文件名的 /files/{name}）。"""
    record = _get_owned_record(db, record_id, principal)
    target = Path(word_generator.ensure_output_dir()) / Path(record.file_name).name
    if not target.is_file():
        raise NotFoundError("生成文件不存在或已被清理")
    return FileResponse(target, filename=target.name, media_type=_MEDIA_TYPE_DOCX)


@router.get("/contract/records/{record_id}/preview")
async def preview_contract_record(
    record_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """生成稿预览元信息（逐页图片，与模板预览同一套转换链路）。"""
    record = _get_owned_record(db, record_id, principal)
    target = Path(word_generator.ensure_output_dir()) / Path(record.file_name).name
    if not target.is_file():
        raise NotFoundError("生成文件不存在或已被清理")
    from app.services import docx_convert

    return ok(await docx_convert.preview_meta(target))


@router.get("/contract/records/{record_id}/preview/{page_no}")
async def preview_contract_record_page(
    record_id: int,
    page_no: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    record = _get_owned_record(db, record_id, principal)
    target = Path(word_generator.ensure_output_dir()) / Path(record.file_name).name
    if not target.is_file():
        raise NotFoundError("生成文件不存在或已被清理")
    from app.services import docx_convert

    png_path = await docx_convert.render_page(target, page_no)
    return FileResponse(png_path, media_type="image/png", content_disposition_type="inline")


@router.delete("/contract/records/{record_id}")
async def delete_contract_record(
    record_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """删除生成记录及其产物。"""
    record = _get_owned_record(db, record_id, principal)
    target = Path(word_generator.ensure_output_dir()) / Path(record.file_name).name
    target.unlink(missing_ok=True)
    db.delete(record)
    db.commit()
    return ok({"id": record_id})


@router.post("/contract/preview")
async def preview_contract_draft(
    request: ContractGenerateRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """按当前取值渲染草稿并返回预览元信息（不落生成记录，可反复调用）。

    这是"填完即预览"的实现：前端在停止输入后调用它，用真实 docxtpl 渲染结果覆盖左侧预览，
    以覆盖前端本地替换搞不定的情况（`{% for %}` 生成的表格行、属性访问等）。
    """
    from app.services import docx_convert

    item = template_service.get_template(db, request.template_id)
    draft_path, preview_id = template_service.render_preview(item, request.variables)
    meta = await docx_convert.preview_meta(draft_path)
    return ok({"preview_id": preview_id, **meta})


@router.get("/contract/preview/{preview_id}")
async def preview_contract_draft_meta(
    preview_id: str,
    current_user: str = Depends(get_current_user),
):
    """已渲染草稿的预览元信息（ID 为取值哈希）。"""
    from app.services import docx_convert

    target = _preview_path(preview_id)
    return ok(await docx_convert.preview_meta(target))


@router.get("/contract/preview/{preview_id}/{page_no}")
async def preview_contract_draft_page(
    preview_id: str,
    page_no: int,
    current_user: str = Depends(get_current_user),
):
    """草稿预览单页图片。"""
    from app.services import docx_convert

    png_path = await docx_convert.render_page(_preview_path(preview_id), page_no)
    return FileResponse(png_path, media_type="image/png", content_disposition_type="inline")


def _preview_path(preview_id: str) -> Path:
    """草稿预览文件路径（只接受哈希形式的 ID，防目录穿越）。"""
    if not preview_id.isalnum() or len(preview_id) > 64:
        raise BizError(message="预览 ID 非法")
    target = Path(settings.CONTRACT_PREVIEW_DIR) / f"{preview_id}.docx"
    if not target.is_file():
        raise NotFoundError("预览已过期，请重新渲染")
    return target


@router.post("/regulation/outline")
async def generate_regulation_outline(
    request: RegulationOutlineRequest,
    current_user: str = Depends(get_current_user),
):
    """规章制度生成第一段（需求⑧）：按需求生成可编辑大纲，用户确认后再生成全文。"""
    outline = await generation_service.generate_outline(request.requirement, current_user)
    return ok({"requirement": request.requirement, "outline_text": outline})


@router.post("/regulation/document")
async def generate_regulation_document(
    request: RegulationDocumentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """规章制度生成第二段：后台生成全文并自动合规审查（不合规自动修正，最多 3 轮）。"""
    task = generation_service.create_task(
        db,
        requirement=request.requirement,
        outline=request.outline,
        created_by=current_user,
    )
    background_tasks.add_task(generation_service.run_regulation_task, task.id)
    return ok({"task_id": task.id, "status": task.status})


@router.get("/regulation/{task_id}")
async def get_regulation_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """查询生成进度与结果（前端轮询；completed / failed 后停止）。"""
    task = generation_service.get_task(db, task_id)
    return ok(_generation_payload(task))


@router.get("/regulation")
async def list_regulation_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """规章制度生成历史。"""
    from sqlalchemy import func, select

    from app.models.generation import GenerationTask

    total = db.execute(select(func.count()).select_from(GenerationTask)).scalar_one()
    rows = (
        db.execute(
            select(GenerationTask)
            .order_by(GenerationTask.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return ok(
        {
            "items": [_generation_payload(t) for t in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.delete("/regulation/{task_id}")
async def delete_regulation_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    task = generation_service.get_task(db, task_id)
    generation_service.delete_task(db, task)
    return ok({"id": task_id})


@router.get("/files/{file_name}")
async def download_generated_file(
    file_name: str,
    current_user: str = Depends(get_current_user),
):
    """下载生成产物（合同/规章制度 Word）。仅允许 outputs/ 下的文件名，防目录穿越。"""
    safe_name = Path(file_name).name
    target = Path(word_generator.ensure_output_dir()) / safe_name
    if not target.exists() or not target.is_file():
        from app.core.exceptions import NotFoundError

        raise NotFoundError("生成文件不存在或已过期")
    return FileResponse(target, filename=safe_name, media_type=_MEDIA_TYPE_DOCX)
