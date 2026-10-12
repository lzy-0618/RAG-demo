"""审查相关请求/响应模型（需求 ②③）。

审查结果是与前端约定的固定 schema，不透传 Dify 的裸 outputs，
以便按「条款原文 + 风险等级 + 违反的法规/制度条款 + 案例 + 修改建议」渲染。
"""

from pydantic import BaseModel, Field


class Violation(BaseModel):
    """违反的法律法规/规章制度条款。"""

    law_name: str = Field("", description="《法律/制度名称》")
    article: str = Field("", description="具体条款，如「第五百零六条」")
    description: str = Field("", description="具体违反/冲突内容")
    link: str | None = Field(None, description="法规链接（可选，后端可从检索来源回填）")


class ReferenceCase(BaseModel):
    """参考的典型案例（制度审查无案例库，恒为空）。"""

    case_name: str = ""
    lesson: str = ""


class Citation(BaseModel):
    document_name: str
    section: str
    url: str


class RiskItem(BaseModel):
    """一处风险。"""

    clause: str = Field("", description="被判定有风险的条款原文")
    risk_level: str = Field("medium", description="high / medium / low")
    violations: list[Violation] = Field(default_factory=list)
    analysis: str = ""
    citations: list[Citation] = Field(default_factory=list)
    case_analysis: str = ""
    needs_review: bool = False
    validation_notes: list[str] = Field(default_factory=list)
    reference_case: ReferenceCase | None = None
    suggestion: str = Field("", description="修改建议")
    chunk_index: int | None = Field(None, description="所在块序号（合并时回填）")
    location: str | None = Field(None, description="定位文案，如「第 3 页」「第 12-18 段」")


class ReviewResult(BaseModel):
    """合并后的完整审查报告。"""

    is_compliant: bool = True
    summary: str = ""
    total_chunks: int = 0
    failed_chunks: int = 0
    failed_details: list[dict] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)


class ActiveReviewChunk(BaseModel):
    index: int
    phase: str  # retrieval / generation


class ReviewProgress(BaseModel):
    stage: str  # upload / parse / review / done
    processed_chunks: int = 0
    active_chunks: list[ActiveReviewChunk] = Field(default_factory=list)


class ReviewTaskOut(BaseModel):
    """审查任务出参（进度 + 结果）。"""

    id: int
    review_type: str
    input_type: str
    source_name: str | None = None
    status: str
    total_chunks: int
    completed_chunks: int
    failed_chunks: int
    is_compliant: bool | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    result: ReviewResult | None = None
    progress: ReviewProgress | None = None

    @classmethod
    def from_model(
        cls, task, result: ReviewResult | None = None, progress: ReviewProgress | None = None
    ) -> "ReviewTaskOut":
        return cls(
            id=task.id,
            review_type=task.review_type,
            input_type=task.input_type,
            source_name=task.source_name,
            status=task.status,
            total_chunks=task.total_chunks,
            completed_chunks=task.completed_chunks,
            failed_chunks=task.failed_chunks,
            is_compliant=task.is_compliant,
            error=task.error,
            created_at=task.created_at.isoformat(sep=" ") if task.created_at else None,
            updated_at=task.updated_at.isoformat(sep=" ") if task.updated_at else None,
            result=result,
            progress=progress,
        )
