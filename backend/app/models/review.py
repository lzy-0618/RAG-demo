"""审查任务数据模型（需求 ②③）。

长文档审查耗时长（解析 → 切块 → 逐块调 Dify 工作流 → 合并），
用任务 + 轮询的方式对外提供进度，避免长连接易断、刷新页面丢进度。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewTask(Base):
    """审查任务。

    status 流转（见 core.constants）：pending → running → completed / failed。
    result_json 存合并后的审查报告（summary + risks），供前端渲染与审计追溯。
    """

    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    review_type: Mapped[str] = mapped_column(String(32), index=True)  # contract / regulation
    input_type: Mapped[str] = mapped_column(String(16), default="text")  # text / file
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    completed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    failed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    is_compliant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
