"""知识库文档数据模型（对应需求 ①⑨）。

本地 Document 记录保存「文件落地 + Dify 文档 ID + 索引状态」，是知识「进」（① 上传入库）
与「管」（⑨ 增删改查）共用同一份元数据的基础。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    """知识库文档元数据。

    状态流转（见 core.constants）：uploaded → parsing → ready / failed。
    dataset_key 取值：law / regulation / case / rule / expert。
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    dataset_key: Mapped[str] = mapped_column(String(32), index=True)
    doc_type: Mapped[str] = mapped_column(String(16), default="file")  # file / text
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dify_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    # Dify 异步索引以 batch 为单位，用于轮询 indexing-status 回写状态
    dify_batch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    uploader: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
