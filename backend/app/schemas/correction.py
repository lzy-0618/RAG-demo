"""内容纠错标注请求/响应模型（需求 ⑤）。"""

from pydantic import BaseModel, Field


class CorrectionCreate(BaseModel):
    """专家提交一条纠错标注：针对某条 AI 回答给出修正内容。"""

    source_content: str = Field(..., min_length=1, description="被纠错的 AI 原回答")
    corrected_content: str = Field(..., min_length=1, description="专家修正后的内容")
    question: str | None = Field(None, description="对应的用户提问（用于生成标注标题）")
    conversation_id: str | None = Field(None, description="会话 ID")
    message_id: str | None = Field(None, description="Dify 消息 ID，用于把标注关联到具体回答")


class CorrectionOut(BaseModel):
    id: int
    question: str | None = None
    source_content: str
    corrected_content: str
    expert: str | None = None
    chat_conversation_id: str | None = None
    chat_message_id: str | None = None
    dataset_id: str | None = None
    document_id: str | None = None
    local_document_id: int | None = None
    write_status: str
    error: str | None = None
    created_at: str | None = None

    @classmethod
    def from_model(cls, item) -> "CorrectionOut":
        return cls(
            id=item.id,
            question=item.question,
            source_content=item.source_content,
            corrected_content=item.corrected_content,
            expert=item.expert,
            chat_conversation_id=item.chat_conversation_id,
            chat_message_id=item.chat_message_id,
            dataset_id=item.dataset_id,
            document_id=item.document_id,
            local_document_id=item.local_document_id,
            write_status=item.write_status,
            error=item.error,
            created_at=item.created_at.isoformat(sep=" ") if item.created_at else None,
        )
