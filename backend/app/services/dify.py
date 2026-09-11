"""Dify 调用统一封装：对外只暴露业务方法，隔离 Dify HTTP 细节。

所有方法均为 async，与 FastAPI 异步链路保持一致；流式方法返回 AsyncGenerator，
由路由层通过 sse-starlette 转成 SSE 推给前端，不在内存中攒完整答案。
"""

import json
from typing import AsyncGenerator

import httpx

from app.core.config import settings


class DifyClient:
    def __init__(self) -> None:
        self.base_url = settings.DIFY_BASE_URL.rstrip("/")

    def _headers(self, api_key: str | None = None) -> dict:
        return {
            "Authorization": f"Bearer {api_key or settings.DIFY_API_KEY}",
            "Content-Type": "application/json",
        }

    async def run_workflow(
        self, api_key: str, inputs: dict, user: str, response_mode: str = "blocking"
    ) -> dict:
        """同步（blocking）执行工作流，适用于合同审查等需要完整结果多步推理的场景。"""
        url = f"{self.base_url}/v1/workflows/run"
        body = {"inputs": inputs, "response_mode": response_mode, "user": user}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=self._headers(api_key))
            resp.raise_for_status()
            return resp.json()

    async def run_workflow_stream(
        self, api_key: str, inputs: dict, user: str
    ) -> AsyncGenerator[dict, None]:
        """流式执行工作流，逐条 yield Dify SSE 事件的 JSON。"""
        url = f"{self.base_url}/v1/workflows/run"
        body = {"inputs": inputs, "response_mode": "streaming", "user": user}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            async with client.stream(
                "POST", url, json=body, headers=self._headers(api_key)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        yield _parse_sse_data(line)

    async def chat(
        self,
        api_key: str,
        query: str,
        user: str,
        conversation_id: str = "",
        inputs: dict | None = None,
    ) -> dict:
        """同步（blocking）RAG 对话。"""
        url = f"{self.base_url}/v1/chat-messages"
        body = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": "blocking",
            "user": user,
            "conversation_id": conversation_id,
        }
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=self._headers(api_key))
            resp.raise_for_status()
            return resp.json()

    async def chat_stream(
        self,
        api_key: str,
        query: str,
        user: str,
        conversation_id: str = "",
        inputs: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """流式 RAG 对话，逐条 yield Dify 的 message / message_end / error 事件。"""
        url = f"{self.base_url}/v1/chat-messages"
        body = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": "streaming",
            "user": user,
            "conversation_id": conversation_id,
        }
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            async with client.stream(
                "POST", url, json=body, headers=self._headers(api_key)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        yield _parse_sse_data(line)

    async def upload_document(
        self, api_key: str, file_path: str, file_name: str, user: str
    ) -> dict:
        """上传文档到 Dify 知识库。"""
        url = f"{self.base_url}/v1/datasets/upload-file"
        headers = {"Authorization": f"Bearer {api_key or settings.DIFY_API_KEY}"}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, "application/octet-stream")}
                data = {"user": user}
                resp = await client.post(url, headers=headers, data=data, files=files)
                resp.raise_for_status()
                return resp.json()

    async def create_document_by_text(
        self, api_key: str, dataset_id: str, name: str, text: str
    ) -> dict:
        """通过文本创建知识库文档。"""
        url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create_by_text"
        body = {"name": name, "text": text, "indexing_technique": "high_quality"}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=self._headers(api_key))
            resp.raise_for_status()
            return resp.json()


def _parse_sse_data(line: str) -> dict:
    """解析 `data: {...}` 形式的 SSE 行，失败时原样保留。"""
    payload = line[len("data:"):].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}


dify_client = DifyClient()
