"""内容纠错反馈数据模型（对应需求 ⑤）。"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CorrectionFeedback(Base):
    __tablename__ = "correction_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_content: Mapped[str] = mapped_column(Text)
    corrected_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/approved/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
