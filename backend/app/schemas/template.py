"""合同模板库与合同生成的请求/响应模型（需求 ⑥⑦）。"""

from pydantic import BaseModel, Field


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = None
    description: str | None = None


class TemplateField(BaseModel):
    """字段 schema：AI 识别 + 人工复核后确定的一项待填内容。

    `anchors` / `candidate_ids` 是**复数**：同一个变量在文档里可能有多处落点（首部与
    签署信息表、浮动文本框的 Choice/Fallback 两份副本），它们共用同一个 key，生成时
    一处填写、多处生效。`slot_id` 是变量的身份，复核页保存后会再回写一次模板，
    靠它才能把所有落点重新写全——所以这些字段必须留在 schema 里，
    不能让 Pydantic 当成未知字段丢掉。
    """

    key: str = Field(..., description="占位符键，合法 Jinja 标识符")
    label: str = Field(..., description="中文标签，前端表单显示名")
    type: str = Field("text", description="text / textarea / date / number / select / checkbox")
    required: bool = False
    default: str = ""
    options: list[str] = Field(default_factory=list, description="type=select 时的候选项")
    anchor: str = Field("", description="文档锚点，如 p12")
    anchors: list[str] = Field(default_factory=list, description="该变量的全部落点")
    candidate_id: str = Field("", description="来源候选 id，供复核页回溯")
    candidate_ids: list[str] = Field(default_factory=list, description="该变量命中的全部候选")
    slot_id: str = Field("", description="字段槽位 id：同名变量共用一个槽位")
    source_name: str = Field("", description="模板里的原名，如 FORMTEXT 域结果 PUR_BILL_TO_NAME")
    owner: str = Field("", description="主体（甲方 / 乙方 / 附件…），用于消解中文标签重名")
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
    """复核页需要的完整上下文：文档结构大纲、候选空位、字段槽位、识别过程留痕。"""

    outline: str = ""
    candidates: list[dict] = Field(default_factory=list)
    slots: list[dict] = Field(default_factory=list)
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
