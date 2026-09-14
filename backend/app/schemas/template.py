"""合同模板库与合同生成的请求/响应模型（需求 ⑥⑦）。"""

from pydantic import BaseModel, Field


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = None
    description: str | None = None


class TemplateField(BaseModel):
    """字段 schema：AI 识别 + 人工复核后确定的一项待填内容。"""

    key: str = Field(..., description="占位符键，合法 Jinja 标识符")
    label: str = Field(..., description="中文标签，前端表单显示名")
    type: str = Field("text", description="text / textarea / date / number / select / checkbox")
    required: bool = False
    default: str = ""
    options: list[str] = Field(default_factory=list, description="type=select 时的候选项")
    anchor: str = Field("", description="文档锚点，如 p12")
    candidate_id: str = Field("", description="来源候选 id，供复核页回溯")
    paragraph_text: str = Field("", description="字段所在段落原文，供复核确认")
    confidence: float = 0.0
    reason: str = ""


class TemplateOut(BaseModel):
    id: int
    name: str
    category: str | None = None
    file_name: str | None = None
    file_size: int = 0
    variables: list[str] = Field(default_factory=list)
    fields: list[TemplateField] = Field(default_factory=list)
    description: str | None = None
    uploader: str | None = None
    structure_status: str = "pending"
    version: int = 1
    standardized: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class TemplateDetailOut(TemplateOut):
    """复核页需要的完整上下文：文档结构大纲、候选空位、识别过程留痕。"""

    outline: str = ""
    candidates: list[dict] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    error: str = ""


class TemplateFieldsRequest(BaseModel):
    """复核确认：保存字段定义并（可选）启用模板。"""

    fields: list[TemplateField]
    contract_type: str | None = None
    enable: bool = True


class CategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    sort_order: int = 0


class ContractGenerateRequest(BaseModel):
    """合同生成请求（需求⑦）：模板 + 字段取值，docxtpl 确定性填充。"""

    template_id: int = Field(..., description="模板 ID")
    variables: dict = Field(default_factory=dict, description="字段取值")


class ContractGenerateOut(BaseModel):
    record_id: int = Field(..., description="生成记录 ID，下载与追溯都走它")
    template_id: int
    template_name: str
    file_name: str
    download_url: str
    missing_variables: list[str] = Field(default_factory=list, description="未填写而补空的变量")


class ContractRecordOut(BaseModel):
    id: int
    template_id: int
    template_name: str
    file_name: str
    file_size: int = 0
    missing_variables: list[str] = Field(default_factory=list)
    values: dict = Field(default_factory=dict)
    created_by: str | None = None
    created_at: str | None = None
