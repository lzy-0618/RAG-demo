"""审查路由：合同审查与规章制度审查（需求 ②③）。

任务式接口：提交后立即返回 task_id，后台异步执行审查并汇总，
前端轮询 GET /review/{task_id} 获取进度与结果（长文档审查耗时可达数分钟，长连接易断）。
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.constants import REVIEW_TYPE_CONTRACT
from app.core.deps import get_current_user, get_db
from app.schemas.common import ok
from app.schemas.review import ReviewTaskOut
from app.services import review as review_service

router = APIRouter(prefix="/review", tags=["审查"])


def _task_payload(task) -> dict:
    return ReviewTaskOut.from_model(task, review_service.parse_result(task)).model_dump()


@router.post("")
async def submit_review(
    background_tasks: BackgroundTasks,
    review_type: str = Form(REVIEW_TYPE_CONTRACT, description="contract / regulation"),
    content: str | None = Form(None, description="待审查文本（与 file 二选一）"),
    file: UploadFile | None = File(None, description="待审查文件 pdf/doc/docx/md/txt"),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """提交审查任务：文本或文件二选一，返回 task_id 供轮询进度。"""
    file_bytes = await file.read() if file else None
    task = await review_service.create_task(
        db,
        review_type=review_type,
        content=content,
        filename=file.filename if file else None,
        file_bytes=file_bytes,
        created_by=current_user,
    )
    # 文件型任务传 source_path；合同由 Dify 提取和切块，制度由后端解析。
    background_tasks.add_task(
        review_service.run_review_task,
        task.id,
        None if file_bytes else content,
    )
    return ok({"task_id": task.id, "status": task.status, "total_chunks": task.total_chunks})


@router.get("/tasks")
async def list_review_tasks(
    review_type: str | None = Query(None, description="按审查类型过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """审查任务列表（用于历史记录与进度回看）。"""
    tasks, total = review_service.list_tasks(
        db, review_type=review_type, page=page, page_size=page_size
    )
    return ok(
        {
            "items": [
                ReviewTaskOut.from_model(t).model_dump() for t in tasks
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{task_id}")
async def get_review_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """查询审查进度与结果：前端按此轮询（completed / failed 后停止轮询）。"""
    task = review_service.get_task(db, task_id)
    return ok(_task_payload(task))


@router.delete("/{task_id}")
async def delete_review_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    task = review_service.get_task(db, task_id)
    review_service.delete_task(db, task)
    return ok({"id": task_id})
