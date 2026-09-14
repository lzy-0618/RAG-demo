"""专家纠错标注数据模型（对应需求 ⑤）。

专家对大模型回答的纠错**无审核环节**：提交即写入「专家知识库」，供后续 RAG 检索引用。
write_status 表示写入知识库是否成功（pending / written / failed），用于失败重试，而不是审核状态。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CorrectionFeedback(Base):
    """一条专家纠错标注记录。"""

    __tablename__ = "correction_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 被纠错的原始提问与 AI 回答
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_content: Mapped[str] = mapped_column(Text)
    corrected_content: Mapped[str] = mapped_column(Text)
    expert: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 定位到具体会话与消息，便于追溯与按回答回看标注
    chat_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chat_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # 写入专家知识库的结果
    dataset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    local_document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    write_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending/written/failed
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
