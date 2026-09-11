"""合同审查相关请求模型。"""

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    content: str = Field(..., min_length=1, description="待审查的合同文本")
    review_type: str = Field("contract", description="审查类型：contract / regulation")
