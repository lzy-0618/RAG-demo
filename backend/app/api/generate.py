"""生成路由：合同生成（需求⑦）与规章制度生成（需求⑧）。

- 合同生成：docxtpl 模板填充，**确定性链路**，不依赖 Dify；
- 规章制度生成：调「规章制度生成」Dify 工作流（大纲 / 全文），全文生成后自动做合规审查，
  不合规时带冲突清单与上一版全文重新生成，最多 3 轮（循环在后端编排）。
"""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.schemas.common import ok
from app.schemas.generate import RegulationDocumentRequest, RegulationOutlineRequest
from app.schemas.template import ContractGenerateOut, ContractGenerateRequest
from app.services import generation as generation_service
from app.services import template as template_service
from app.services import word_generator

router = APIRouter(prefix="/generate", tags=["生成"])

_MEDIA_TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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


@router.post("/contract")
async def generate_contract(
    request: ContractGenerateRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """合同生成（需求⑦）：按模板填充变量，返回可下载的 Word 初稿。"""
    item = template_service.get_template(db, request.template_id)
    file_path, file_name = template_service.render_contract(db, item, request.variables)
    declared = template_service.parse_variables(item)
    missing = [key for key in declared if not str(request.variables.get(key) or "").strip()]
    return ok(
        ContractGenerateOut(
            template_id=item.id,
            template_name=item.name,
            file_name=file_name,
            download_url=f"/api/v1/generate/files/{file_name}",
            missing_variables=missing,
        ).model_dump()
    )


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
