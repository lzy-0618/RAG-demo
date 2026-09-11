"""知识库相关请求/响应模型。"""

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    dataset_id: str | None = None


class DocumentOut(BaseModel):
    id: int
    title: str
    status: str
    created_at: str | None = None
