"""合同模板数据模型（对应需求 ⑥）。

模板为含 `{{ 变量 }}` 占位符的 .docx 文件，供需求⑦的 docxtpl 填充生成合同初稿。
导入时解析占位变量并缓存到 variables_json，前端据此动态渲染填报表单。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContractTemplate(Base):
    __tablename__ = "contract_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    # 模板占位变量列表的 JSON 缓存（docxtpl get_undeclared_template_variables）
    variables_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploader: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
