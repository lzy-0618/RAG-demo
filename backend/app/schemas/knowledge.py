"""知识库相关请求/响应模型。"""

from pydantic import BaseModel, Field


class DatasetOut(BaseModel):
    """知识库（Dify dataset）出参。"""

    key: str = Field(..., description="知识库标识：law/regulation/case/rule/expert")
    name: str = Field(..., description="知识库展示名")
    dataset_id: str = Field("", description="Dify dataset_id，未配置时为空")
    configured: bool = Field(False, description="后端 .env 是否已配置该 dataset_id")
    document_count: int = Field(0, description="本地记录的文档数")


class TextDocumentCreate(BaseModel):
    """创建文本型文档（审核规则、专家标注等以文本为主的场景）。"""

    dataset_key: str = Field(..., description="知识库标识：law/regulation/case/rule/expert")
    title: str = Field(..., min_length=1, max_length=255)
    text: str = Field(..., min_length=1, description="文本内容")


class ChunkUpdate(BaseModel):
    content: str = Field(..., min_length=1, description="修改后的分块内容")


class DocumentOut(BaseModel):
    """知识库文档出参（本地元数据）。"""

    id: int
    title: str
    dataset_key: str
    doc_type: str
    status: str
    dify_document_id: str | None = None
    uploader: str | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_model(cls, doc) -> "DocumentOut":
        return cls(
            id=doc.id,
            title=doc.title,
            dataset_key=doc.dataset_key,
            doc_type=doc.doc_type,
            status=doc.status,
            dify_document_id=doc.dify_document_id,
            uploader=doc.uploader,
            error=doc.error,
            created_at=doc.created_at.isoformat(sep=" ") if doc.created_at else None,
            updated_at=doc.updated_at.isoformat(sep=" ") if doc.updated_at else None,
        )
