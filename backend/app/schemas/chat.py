"""对话相关请求/响应模型。"""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=20000, description="用户提问")
    conversation_id: str = Field("", description="会话 ID，为空则新建会话")
    inputs: dict = Field(default_factory=dict, description="额外变量（Dify 工作流输入）")


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str = ""
    sources: list = Field(default_factory=list)
