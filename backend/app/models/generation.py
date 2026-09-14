"""规章制度生成任务模型（需求 ⑧）。

两段式（大纲 → 全文）+ 生成后自动合规审查与修正循环，整体耗时可达数分钟，
因此用任务 + 轮询：round 表示已完成的修正轮次（0 为首版），最多 max_rounds 轮。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requirement: Mapped[str] = mapped_column(Text)
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # 修正轮次：0 = 首版，1..max_rounds = 自动修正轮
    round: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=3)
    # 当前轮次的审查进度
    review_round: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    completed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    failed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    is_compliant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 最终产物：结构化章节、最新审查结果、Word 文件
    sections_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    doc_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
