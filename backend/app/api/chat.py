"""对话路由：RAG 问答（需求 ③④），支持阻塞式与 SSE 流式。"""

import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.deps import get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.dify import dify_client

router = APIRouter(prefix="/chat", tags=["对话"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: str = Depends(get_current_user)):
    """阻塞式对话（同步返回完整答案）。"""
    result = await dify_client.chat(
        api_key=settings.DIFY_API_KEY,
        query=request.query,
        user=current_user,
        conversation_id=request.conversation_id,
        inputs=request.inputs,
    )
    return ChatResponse(
        answer=result.get("answer", ""),
        conversation_id=result.get("conversation_id", ""),
        sources=result.get("metadata", {}).get("retriever_resources", []),
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, current_user: str = Depends(get_current_user)):
    """流式对话：将 Dify 的 message/message_end/error 事件转成 SSE。"""

    async def event_generator():
        async for event in dify_client.chat_stream(
            api_key=settings.DIFY_API_KEY,
            query=request.query,
            user=current_user,
            conversation_id=request.conversation_id,
            inputs=request.inputs,
        ):
            event_name = event.get("event", "message")
            yield {
                "event": event_name,
                "data": json.dumps(event, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())
