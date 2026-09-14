"""合同模板数据模型（对应需求 ⑥）。

模板的形态分两份文件：

- `source_path`：用户上传的原始 .docx（**必须保留**，识别不满意时可重跑，不必让用户重传）；
- `standardized_path`：结构化后的模板（占位符已规范化为 `{{ key }}`），生成阶段用这一份。

`fields_json` 存字段 schema（中文标签 / 控件类型 / 是否必填等），前端据此渲染填报表单；
`structure_meta_json` 存识别过程留痕（候选数、模型原始输出、警告、自检结果），便于排查与重跑。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# 结构化状态机
STRUCTURE_PENDING = "pending"  # 待识别
STRUCTURE_STRUCTURING = "structuring"  # 识别中
STRUCTURE_REVIEW = "review"  # 待复核
STRUCTURE_READY = "ready"  # 已启用
STRUCTURE_FAILED = "failed"  # 识别失败


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

    # ===== 结构化（P1/P2）=====
    source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    standardized_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    structure_status: Mapped[str] = mapped_column(
        String(16), default=STRUCTURE_PENDING, index=True
    )
    structure_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TemplateCategory(Base):
    """合同类型受控词表（需求⑥⑦）。

    原先 `category` 是用户手打的自由文本，会出现"采购 / 采购类 / 采购合同"并存；
    改为词表后，导入时从下拉选择、生成页按类型筛模板。
    """

    __tablename__ = "template_categories"
    __table_args__ = (UniqueConstraint("name", name="uq_template_category_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
