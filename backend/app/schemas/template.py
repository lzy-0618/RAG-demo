"""合同模板库请求/响应模型（需求 ⑥）。"""

from pydantic import BaseModel, Field


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = None
    description: str | None = None


class TemplateOut(BaseModel):
    id: int
    name: str
    category: str | None = None
    file_name: str | None = None
    file_size: int = 0
    variables: list[str] = Field(default_factory=list)
    description: str | None = None
    uploader: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_model(cls, item, variables: list[str]) -> "TemplateOut":
        return cls(
            id=item.id,
            name=item.name,
            category=item.category,
            file_name=item.file_name,
            file_size=item.file_size or 0,
            variables=variables,
            description=item.description,
            uploader=item.uploader,
            created_at=item.created_at.isoformat(sep=" ") if item.created_at else None,
            updated_at=item.updated_at.isoformat(sep=" ") if item.updated_at else None,
        )


class ContractGenerateRequest(BaseModel):
    """合同生成请求（需求⑦）：模板 + 变量，docxtpl 确定性填充。"""

    template_id: int = Field(..., description="模板 ID")
    variables: dict = Field(default_factory=dict, description="模板占位变量取值")


class ContractGenerateOut(BaseModel):
    template_id: int
    template_name: str
    file_name: str
    download_url: str
    missing_variables: list[str] = Field(default_factory=list, description="未填写而补空的变量")
