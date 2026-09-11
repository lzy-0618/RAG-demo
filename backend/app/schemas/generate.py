"""合同/规章制度生成相关请求模型。"""

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    template_name: str | None = Field(None, description="模板名称，为空则走大纲生成")
    outline: str | None = Field(None, description="大纲/要点文本")
    variables: dict = Field(default_factory=dict, description="模板填充变量")
