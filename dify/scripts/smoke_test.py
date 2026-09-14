#!/usr/bin/env python3
"""四个 Dify 应用的端到端冒烟测试。

运行方式（必须在 backend 目录下、用后端虚拟环境，以便读取 .env）：

    cd backend && .venv/bin/python ../dify/scripts/smoke_test.py

校验四条业务链路是否真正可用（不只是 HTTP 200，而是输出内容符合预期）：
  1. 合同审查：传含明显违规条款的合同 → 期望 is_compliant=false 且 risks 非空
  2. 制度审查：传与现行制度冲突的制度条款 → 期望 is_compliant=false 且 risks 非空
  3. 合规咨询：提问 → 期望有回答且带引用来源
  4. 规章制度生成：mode=outline → 期望返回大纲文本、sections_json 为空
"""

import asyncio
import json
import os
import sys
import time

import httpx

# 从 backend 目录运行时导入 app 包（脚本自身目录不在 sys.path 中）
sys.path.insert(0, os.getcwd())

from app.core.config import settings  # noqa: E402

BASE = settings.DIFY_BASE_URL.rstrip("/")

CONTRACT_TEXT = """第三条 因履行合同造成对方人身伤害的，本公司不承担任何赔偿责任。
第四条 乙方交付的钢材质量以甲方现场验收为准，甲方有权单方决定是否合格。"""

REGULATION_TEXT = """第五条 员工出差住宿费实行实报实销，不设上限，无需部门负责人审批。
第六条 采购金额在50万元以下的，可由采购员自行确定供应商并签订合同，无需招标。"""


async def _post(client: httpx.AsyncClient, path: str, key: str, body: dict) -> tuple[int, dict, float]:
    t0 = time.time()
    resp = await client.post(f"{BASE}{path}", json=body, headers={"Authorization": f"Bearer {key}"})
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    return resp.status_code, data, time.time() - t0


async def check_contract_review(client: httpx.AsyncClient) -> tuple[bool, str]:
    code, data, cost = await _post(
        client, "/v1/workflows/run", settings.DIFY_CONTRACT_REVIEW_APP_KEY,
        {"inputs": {"chunk_text": CONTRACT_TEXT}, "response_mode": "blocking", "user": "smoke"},
    )
    out = (data.get("data") or {}).get("outputs") or {}
    risks = out.get("risks") or []
    ok = code == 200 and out.get("is_compliant") == "false" and len(risks) > 0
    detail = f"{cost:.1f}s is_compliant={out.get('is_compliant')} risks={len(risks)}"
    if risks:
        detail += f" 首条依据={risks[0].get('violations', [{}])[0].get('law_name', '?')}"
    return ok, detail


async def check_regulation_review(client: httpx.AsyncClient) -> tuple[bool, str]:
    code, data, cost = await _post(
        client, "/v1/workflows/run", settings.DIFY_REGULATION_REVIEW_APP_KEY,
        {"inputs": {"chunk_text": REGULATION_TEXT}, "response_mode": "blocking", "user": "smoke"},
    )
    out = (data.get("data") or {}).get("outputs") or {}
    risks = out.get("risks") or []
    ok = code == 200 and out.get("is_compliant") == "false" and len(risks) > 0
    return ok, f"{cost:.1f}s is_compliant={out.get('is_compliant')} risks={len(risks)}"


async def check_chatflow(client: httpx.AsyncClient) -> tuple[bool, str]:
    code, data, cost = await _post(
        client, "/v1/chat-messages", settings.DIFY_CHAT_APP_KEY,
        {"inputs": {"category": "差旅"}, "query": "差旅住宿标准是多少？",
         "response_mode": "blocking", "user": "smoke", "conversation_id": ""},
    )
    answer = str(data.get("answer") or "")
    sources = (data.get("metadata") or {}).get("retriever_resources") or []
    ok = code == 200 and len(answer) > 20 and len(sources) > 0
    return ok, f"{cost:.1f}s 回答 {len(answer)} 字 | 引用来源 {len(sources)} 条"


async def check_generation(client: httpx.AsyncClient) -> tuple[bool, str]:
    code, data, cost = await _post(
        client, "/v1/workflows/run", settings.DIFY_GENERATE_APP_KEY,
        {"inputs": {"requirement": "制定一份钢材采购管理办法，明确采购申请、供应商选择、合同签订与验收付款流程",
                    "mode": "outline"},
         "response_mode": "blocking", "user": "smoke"},
    )
    out = (data.get("data") or {}).get("outputs") or {}
    outline = str(out.get("outline_text") or "")
    ok = code == 200 and len(outline) > 100 and not out.get("sections_json")
    return ok, f"{cost:.1f}s 大纲 {len(outline)} 字 | sections_json 为空={not out.get('sections_json')}"


CASES = [
    ("合同审查", check_contract_review),
    ("制度审查", check_regulation_review),
    ("合规咨询", check_chatflow),
    ("规章制度生成", check_generation),
]


async def main() -> int:
    missing = [name for name, _ in CASES if not {
        "合同审查": settings.DIFY_CONTRACT_REVIEW_APP_KEY,
        "制度审查": settings.DIFY_REGULATION_REVIEW_APP_KEY,
        "合规咨询": settings.DIFY_CHAT_APP_KEY,
        "规章制度生成": settings.DIFY_GENERATE_APP_KEY,
    }[name]]
    if missing:
        print(f"以下应用的 API Key 未配置：{missing}", file=sys.stderr)
        return 2

    failed = 0
    async with httpx.AsyncClient(timeout=300) as client:
        for name, fn in CASES:
            try:
                ok, detail = await fn(client)
            except Exception as exc:  # noqa: BLE001 - 冒烟脚本需要打印原始异常
                ok, detail = False, f"异常：{exc}"
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
            failed += 0 if ok else 1
    print(f"\n{'全部通过' if not failed else f'{failed} 项失败'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
