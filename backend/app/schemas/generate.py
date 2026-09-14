"""规章制度生成相关请求模型（需求 ⑧）。

两段式：先按需求生成大纲供用户确认，再用确认后的大纲生成全文并自动合规审查。
"""

from pydantic import BaseModel, Field


class RegulationOutlineRequest(BaseModel):
    """第一段：按需求生成大纲。"""

    requirement: str = Field(..., min_length=1, description="规章制度的内容需求描述")


class RegulationDocumentRequest(BaseModel):
    """第二段：按确认后的大纲生成全文（并自动审查 + 最多 3 轮修正）。"""

    requirement: str = Field(..., min_length=1, description="规章制度的内容需求描述")
    outline: str = Field(..., min_length=1, description="用户确认后的大纲文本")
