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

    async def run_template_structure(
        self,
        api_key: str,
        *,
        doc_outline: str,
        candidates_json: str,
        template_name: str,
        user: str,
    ) -> dict:
        """执行「合同模板结构化」工作流（应用六），返回 outputs。

        输入是后端扫描出的文档结构大纲与候选空位清单，输出是待填字段清单 JSON
        （fields_json）与解析失败标志（parse_error）。
        """
        inputs = {
            "doc_outline": doc_outline,
            "candidates_json": candidates_json,
            "template_name": template_name,
        }
        result = await self.run_workflow(api_key=api_key, inputs=inputs, user=user)
        return (result.get("data") or {}).get("outputs") or {}

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

    async def upload_file(self, api_key: str, file_path: str, file_name: str, user: str = "rag-demo") -> dict:
        """上传独立文件到 Dify（/v1/files/upload）。

        注意：知识库入库不用此接口——1.17 的 create_by_file 直接接收 multipart 文件，
        本方法留给后续「对话附件」等需要 file_id 的场景。
        """
        url = f"{self.base_url}/v1/files/upload"
        headers = {"Authorization": f"Bearer {api_key or settings.DIFY_API_KEY}"}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, "application/octet-stream")}
                data = {"user": user}
                resp = await client.post(url, headers=headers, data=data, files=files)
                resp.raise_for_status()
                return resp.json()

    async def get_dataset(self, api_key: str, dataset_id: str) -> dict:
        """查询知识库详情（含 doc_form 等分段结构设置）。

        create_by_text / create_by_file 必须传入与知识库一致的 doc_form，
        否则 Dify 返回 400「doc_form is different from the dataset doc_form」。
        """
        url = f"{self.base_url}/v1/datasets/{dataset_id}"
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers(api_key))
            _ensure_ok(resp, "查询知识库详情")
            return resp.json()

    def _process_rule(self, max_tokens: int, chunk_overlap: int) -> dict:
        """自定义分段规则（500 token / 15% 重叠）。仅在明确需要覆盖库设置时使用。

        注意：Dify 要求 pre_processing_rules 必填；父子分段（hierarchical_model）的库
        直接用库自身默认规则即可，显式传 custom 规则会被拒绝。
        """
        return {
            "mode": "custom",
            "rules": {
                "pre_processing_rules": [
                    {"id": "remove_extra_spaces", "enabled": True},
                    {"id": "remove_urls_emails", "enabled": False},
                ],
                "segmentation": {
                    "separator": "\n\n",
                    "max_tokens": max_tokens,
                    "chunk_overlap": chunk_overlap,
                },
            },
        }

    async def create_document_by_text(
        self,
        api_key: str,
        dataset_id: str,
        name: str,
        text: str,
        doc_form: str | None = None,
        process_rule: dict | None = None,
    ) -> dict:
        """通过文本创建知识库文档（审核规则、专家纠错等文本为主的场景）。

        - doc_form 必须与知识库一致（由调用方通过 get_dataset 获取后传入）；
        - process_rule 默认不传，沿用知识库自身分段设置；
        - 返回含 batch 字段，用于 indexing_status 轮询。
        """
        url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create_by_text"
        body: dict = {"name": name, "text": text, "indexing_technique": "high_quality"}
        if doc_form:
            body["doc_form"] = doc_form
        if process_rule:
            body["process_rule"] = process_rule
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=self._headers(api_key))
            _ensure_ok(resp, "创建文本文档")
            return resp.json()

    async def create_document_by_file(
        self,
        api_key: str,
        dataset_id: str,
        file_path: str,
        file_name: str,
        doc_form: str | None = None,
        process_rule: dict | None = None,
        mime_type: str = "application/octet-stream",
    ) -> dict:
        """上传文件并创建知识库文档（Dify 1.17 的 create_by_file 直接收 multipart）。

        配置通过 `data` 表单字段以 JSON 字符串传递；返回含 batch 字段。
        """
        url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create_by_file"
        config: dict = {"indexing_technique": "high_quality"}
        if doc_form:
            config["doc_form"] = doc_form
        if process_rule:
            config["process_rule"] = process_rule
        headers = {"Authorization": f"Bearer {api_key or settings.DIFY_API_KEY}"}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, mime_type)}
                data = {"data": json.dumps(config, ensure_ascii=False)}
                resp = await client.post(url, headers=headers, data=data, files=files)
                _ensure_ok(resp, "上传文件创建文档")
                return resp.json()

    async def list_documents(
        self,
        api_key: str,
        dataset_id: str,
        page: int = 1,
        limit: int = 20,
        keyword: str = "",
    ) -> dict:
        """列出知识库下的文档（知识库维护：列表页）。"""
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents"
        params: dict = {"page": page, "limit": limit}
        if keyword:
            params["keyword"] = keyword
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.get(url, params=params, headers=self._headers(api_key))
            _ensure_ok(resp, "查询文档列表")
            return resp.json()

    async def get_document(self, api_key: str, dataset_id: str, document_id: str) -> dict:
        """查询单个文档详情（含索引状态）。"""
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers(api_key))
            _ensure_ok(resp, "查询文档详情")
            return resp.json()

    async def indexing_status(self, api_key: str, dataset_id: str, batch_id: str) -> dict:
        """按批次查询文档索引状态（上传后异步索引，轮询更新 Document.status）。

        batch 为 create_document_by_* 返回值中的 batch 字段。
        """
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{batch_id}/indexing-status"
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.get(url, headers=self._headers(api_key))
            _ensure_ok(resp, "查询索引状态")
            return resp.json()

    async def update_document_by_text(
        self,
        api_key: str,
        dataset_id: str,
        document_id: str,
        name: str,
        text: str,
        doc_form: str | None = None,
        process_rule: dict | None = None,
    ) -> dict:
        """更新文本型知识库文档（知识库维护：内容修改）。"""
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}/update_by_text"
        body: dict = {"name": name, "text": text, "indexing_technique": "high_quality"}
        if doc_form:
            body["doc_form"] = doc_form
        if process_rule:
            body["process_rule"] = process_rule
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=self._headers(api_key))
            _ensure_ok(resp, "更新文本文档")
            return resp.json()

    async def update_document_by_file(
        self,
        api_key: str,
        dataset_id: str,
        document_id: str,
        file_path: str,
        file_name: str,
        doc_form: str | None = None,
        process_rule: dict | None = None,
        mime_type: str = "application/octet-stream",
    ) -> dict:
        """更新文件型知识库文档（保留文档 ID，避免删除重建导致引用失效）。"""
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}/update_by_file"
        config: dict = {"indexing_technique": "high_quality"}
        if doc_form:
            config["doc_form"] = doc_form
        if process_rule:
            config["process_rule"] = process_rule
        headers = {"Authorization": f"Bearer {api_key or settings.DIFY_API_KEY}"}
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            with open(file_path, "rb") as f:
                files = {"file": (file_name, f, mime_type)}
                data = {"data": json.dumps(config, ensure_ascii=False)}
                resp = await client.post(url, headers=headers, data=data, files=files)
                _ensure_ok(resp, "更新文件文档")
                return resp.json()

    async def delete_document(self, api_key: str, dataset_id: str, document_id: str) -> dict:
        """删除知识库文档（Dify 成功时返回 204 无响应体，需同步删除本地记录）。"""
        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.delete(url, headers=self._headers(api_key))
            _ensure_ok(resp, "删除文档")
            return resp.json() if resp.status_code != 204 and resp.content else {}

    async def list_datasets(self, page: int = 1, limit: int = 100) -> dict:
        """列出知识库（数据集），用于联通性检查与知识库维护（需知识库 API Key）。"""
        url = f"{self.base_url}/v1/datasets"
        async with httpx.AsyncClient(timeout=settings.DIFY_TIMEOUT) as client:
            resp = await client.get(
                url, params={"page": page, "limit": limit}, headers=self._headers()
            )
            _ensure_ok(resp, "查询知识库列表")
            return resp.json()


def _parse_sse_data(line: str) -> dict:
    """解析 `data: {...}` 形式的 SSE 行，失败时原样保留。"""
    payload = line[len("data:"):].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"raw": payload}


def _ensure_ok(resp: httpx.Response, action: str) -> None:
    """知识库接口的错误处理：把 Dify 的响应体带进异常，便于定位 400 原因。

    Dify 的 400 形如 {"code":"invalid_param","message":"doc_form is different ..."}，
    只抛状态码会让排查变成猜谜。
    """
    if resp.status_code < 400:
        return
    detail = resp.text[:500].replace("\n", " ")
    raise RuntimeError(f"{action}失败（HTTP {resp.status_code}）：{detail}")


dify_client = DifyClient()
