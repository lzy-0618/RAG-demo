"""对话路由：RAG 问答（需求 ④），支持阻塞式与 SSE 流式。

对应 Dify 应用「合规咨询」（Chatflow），多轮上下文由 Dify 的 conversation_id 维护。
"""

import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.deps import get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.dify import dify_client

router = APIRouter(prefix="/chat", tags=["对话"])


def _chat_app_key() -> str:
    """对话走「合规咨询」应用：优先应用级 Key，未配置时回退知识库 Key。"""
    return settings.DIFY_CHAT_APP_KEY or settings.DIFY_API_KEY


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: str = Depends(get_current_user)):
    """阻塞式对话（同步返回完整答案）。"""
    result = await dify_client.chat(
        api_key=_chat_app_key(),
        query=request.query,
        user=current_user,
        conversation_id=request.conversation_id,
        inputs=request.inputs or {},
    )
    return ChatResponse(
        answer=result.get("answer", ""),
        conversation_id=result.get("conversation_id", ""),
        sources=(result.get("metadata") or {}).get("retriever_resources") or [],
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, current_user: str = Depends(get_current_user)):
    """流式对话：把 Dify 的 message / message_end 转成 SSE。

    额外补一个 `sources` 事件（从 message_end 的 metadata 提取引用来源），
    前端不必自己解析 Dify 的元数据结构。
    """

    async def event_generator():
        try:
            async for event in dify_client.chat_stream(
                api_key=_chat_app_key(),
                query=request.query,
                user=current_user,
                conversation_id=request.conversation_id,
                inputs=request.inputs or {},
            ):
                event_name = event.get("event", "message")
                if event_name == "message_end":
                    sources = (event.get("metadata") or {}).get("retriever_resources") or []
                    yield {
                        "event": "sources",
                        "data": json.dumps({"sources": sources}, ensure_ascii=False),
                    }
                    yield {
                        "event": "message_end",
                        "data": json.dumps(
                            {
                                "conversation_id": event.get("conversation_id", ""),
                                "message_id": event.get("id", ""),
                            },
                            ensure_ascii=False,
                        ),
                    }
                    continue
                yield {
                    "event": event_name,
                    "data": json.dumps(event, ensure_ascii=False),
                }
        except Exception as exc:  # noqa: BLE001 - 流式过程出错要以事件下发，而不是直接断开连接
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())
