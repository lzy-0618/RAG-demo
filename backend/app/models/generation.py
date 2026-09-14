"""生成任务与生成记录模型（需求 ⑦⑧）。

- `GenerationTask`：规章制度生成。两段式（大纲 → 全文）+ 生成后自动合规审查与修正循环，
  整体耗时可达数分钟，因此用任务 + 轮询：round 表示已完成的修正轮次（0 为首版）。
- `ContractGeneration`：合同生成记录。合同生成是确定性填充（秒级完成），不需要任务轮询，
  但必须落库——否则产物是 outputs/ 里的裸文件，没有归属、无法追溯，下载也校验不了权限。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContractGeneration(Base):
    """合同生成记录（需求⑦）。

    `template_name` 存快照：模板改名或删除后，历史记录仍然可读。
    `file_name` 用 uuid 片段命名，避免同模板同秒生成互相覆盖。
    """

    __tablename__ = "contract_generations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(Integer, index=True)
    template_name: Mapped[str] = mapped_column(String(255))
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    values_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    missing_variables_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requirement: Mapped[str] = mapped_column(Text)
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # 当前阶段：generating（正在撰写/修正全文）/ reviewing（正在合规审查）/ done
    # 前端据此区分「写作中显示动效进度条」与「审查中显示确定进度」
    phase: Mapped[str] = mapped_column(String(32), default="generating")
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
