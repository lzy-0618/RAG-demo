"""内容纠错业务逻辑（需求 ⑤）：专家标注 → 直接写入专家知识库，无审核环节。

知识库写入复用 knowledge 服务（Dify create_by_text），因此标注内容与普通文档一样
参与后续 RAG 检索——这正是「模型下次回答自动参考专家修正」的闭环。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizError, NotFoundError
from app.models.feedback import CorrectionFeedback
from app.services import knowledge as knowledge_service

# 专家标注统一写入「专家知识库」
EXPERT_DATASET_KEY = "expert"
WRITE_STATUS_WRITTEN = "written"
WRITE_STATUS_FAILED = "failed"

# 单条标注写入知识库的最大长度（Dify 单文档上限较宽松，此处防误贴超长内容）
MAX_CORRECTION_CHARS = 20000


def _build_document_title(question: str | None, correction_id: int | None) -> str:
    """标题便于在知识库列表中辨识，也参与检索。"""
    if question:
        return f"专家标注：{question.strip()[:60]}"
    return f"专家标注-{correction_id}" if correction_id else "专家标注"


def _build_document_text(
    *, question: str | None, source: str, corrected: str, expert: str | None
) -> str:
    """组织成自包含的标注文本，便于检索命中后模型直接引用。"""
    parts = ["【专家纠正标注】"]
    if question:
        parts.append(f"用户问题：{question.strip()}")
    parts.append(f"原 AI 回答：{source.strip()}")
    parts.append(f"专家修正内容（以此为准）：{corrected.strip()}")
    if expert:
        parts.append(f"标注人：{expert}")
    return "\n\n".join(parts)


async def create_correction(
    db: Session,
    *,
    source_content: str,
    corrected_content: str,
    question: str | None,
    conversation_id: str | None,
    message_id: str | None,
    expert: str | None,
) -> CorrectionFeedback:
    """提交专家标注：先落库（pending），再写专家知识库并回写结果。"""
    if len(corrected_content) > MAX_CORRECTION_CHARS:
        raise BizError(message=f"修正内容过长（上限 {MAX_CORRECTION_CHARS} 字）")

    item = CorrectionFeedback(
        question=question,
        source_content=source_content,
        corrected_content=corrected_content,
        expert=expert,
        chat_conversation_id=conversation_id,
        chat_message_id=message_id,
        write_status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    try:
        doc = await knowledge_service.create_text_document(
            db,
            dataset_key=EXPERT_DATASET_KEY,
            title=_build_document_title(question, item.id),
            text=_build_document_text(
                question=question,
                source=source_content,
                corrected=corrected_content,
                expert=expert,
            ),
            uploader=expert,
        )
    except Exception as exc:  # noqa: BLE001 - 写库失败要落库状态供专家重试，不丢标注内容
        item.write_status = WRITE_STATUS_FAILED
        item.error = str(exc)[:500]
        db.commit()
        db.refresh(item)
        return item

    item.dataset_id = settings.DATASET_ID_EXPERT or None
    item.document_id = doc.dify_document_id
    item.local_document_id = doc.id
    item.write_status = WRITE_STATUS_WRITTEN
    item.error = None
    db.commit()
    db.refresh(item)
    return item


async def retry_write(db: Session, item: CorrectionFeedback) -> CorrectionFeedback:
    """写库失败后重试（例如 Dify 临时不可用）。"""
    if item.write_status == WRITE_STATUS_WRITTEN:
        return item
    try:
        doc = await knowledge_service.create_text_document(
            db,
            dataset_key=EXPERT_DATASET_KEY,
            title=_build_document_title(item.question, item.id),
            text=_build_document_text(
                question=item.question,
                source=item.source_content,
                corrected=item.corrected_content,
                expert=item.expert,
            ),
            uploader=item.expert,
        )
    except Exception as exc:  # noqa: BLE001 - 失败原因要落库供前端展示
        item.write_status = WRITE_STATUS_FAILED
        item.error = str(exc)[:500]
        db.commit()
        db.refresh(item)
        return item

    item.document_id = doc.dify_document_id
    item.local_document_id = doc.id
    item.write_status = WRITE_STATUS_WRITTEN
    item.error = None
    db.commit()
    db.refresh(item)
    return item


def get_correction(db: Session, correction_id: int) -> CorrectionFeedback:
    item = db.get(CorrectionFeedback, correction_id)
    if item is None:
        raise NotFoundError("纠错标注不存在")
    return item


def list_corrections(
    db: Session, *, expert: str | None = None, message_id: str | None = None,
    page: int = 1, page_size: int = 20,
) -> tuple[list[CorrectionFeedback], int]:
    stmt = select(CorrectionFeedback)
    count_stmt = select(func.count()).select_from(CorrectionFeedback)
    if expert:
        stmt = stmt.where(CorrectionFeedback.expert == expert)
        count_stmt = count_stmt.where(CorrectionFeedback.expert == expert)
    if message_id:
        stmt = stmt.where(CorrectionFeedback.chat_message_id == message_id)
        count_stmt = count_stmt.where(CorrectionFeedback.chat_message_id == message_id)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(CorrectionFeedback.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def delete_correction(db: Session, item: CorrectionFeedback) -> None:
    """删除标注：连同其在专家知识库中生成的文档一起删除（保持知识库干净）。"""
    if item.local_document_id:
        doc = await _find_document(db, item.local_document_id)
        if doc is not None:
            await knowledge_service.delete_document(db, doc)
    db.delete(item)
    db.commit()


async def _find_document(db: Session, document_id: int):
    from app.models.document import Document

    return db.get(Document, document_id)
