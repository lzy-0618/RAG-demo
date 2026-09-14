"""字段识别的 AI 侧封装（P2 工序 2）：把扫描结果交给 Dify 应用六，解析回字段清单。

职责边界：这里只负责"问模型 + 解析模型输出"，**不碰文档也不碰数据库**。
定位（锚点）来自 P1 的确定性扫描，写回由 P1 的回写模块完成——
AI 出错的影响被限制在"字段列错了"，而不是"合同内容错了"。
"""

import json
import re

from app.core.config import settings
from app.core.exceptions import BizError
from app.services import template_scan
from app.services.dify import dify_client

# 关闭思考模式后仍可能出现思维链残留，解析前先剥离
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

MAX_CANDIDATES = 400


def api_key() -> str:
    return settings.DIFY_TEMPLATE_STRUCTURE_APP_KEY or settings.DIFY_API_KEY


def _last_json_object(text: str, key: str) -> dict | None:
    """从后往前取最后一个含目标键的合法 JSON 对象。

    直接"首个 `{` 到最后一个 `}`"会把思维链里的示例一起圈进来，因此逐个候选起点反解。
    """
    decoder = json.JSONDecoder()
    starts = [match.start() for match in re.finditer(r"\{", text)]
    for start in reversed(starts):
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and key in obj:
            return obj
    return None


def parse_payload(raw: str) -> tuple[dict, bool]:
    """解析模型输出，返回 (payload, parse_error)。"""
    text = _THINK_RE.sub("", raw or "")
    # 优先看 fenced 代码块，再回退全文扫描（坏 fenced 块不应遮蔽后面的合法对象）
    blobs = [*_FENCE_RE.findall(text), text]
    for blob in blobs:
        found = _last_json_object(blob, "fields")
        if found is not None:
            return found, False
    return {}, True


async def identify_fields(scan: template_scan.ScanResult, template_name: str, user: str) -> dict:
    """调用 Dify 识别待填字段，返回 {fields, contract_type, ignored, notes, raw}。"""
    if not api_key():
        raise BizError(
            message="未配置「合同模板结构化」应用 Key（DIFY_TEMPLATE_STRUCTURE_APP_KEY），"
            "请先导入 dify/dsl/合同模板结构化.yml 并填入 .env"
        )
    candidates = template_scan.candidates_for_ai(scan.candidates)
    if len(candidates) > MAX_CANDIDATES:
        candidates = candidates[:MAX_CANDIDATES]

    outputs = await dify_client.run_template_structure(
        api_key=api_key(),
        doc_outline=scan.outline,
        candidates_json=json.dumps(candidates, ensure_ascii=False),
        template_name=template_name,
        user=user,
    )

    raw = str(outputs.get("fields_json") or "")
    payload, parse_failed = parse_payload(raw)
    if str(outputs.get("parse_error") or "").strip().lower() == "true" or parse_failed:
        raise BizError(message="字段识别结果解析失败，请重试或检查 Dify 应用的 Code 节点")

    fields = payload.get("fields")
    if not isinstance(fields, list) or not fields:
        raise BizError(
            message="未识别到任何待填字段。可能是模板中没有可识别的位置"
            "（既没有 {{ 占位符 }}，也没有下划线填空或空标签），请检查模板内容"
        )

    # 回填候选原文，供复核页展示"这个字段来自文档的哪一处"
    for field in fields:
        if not isinstance(field, dict):
            continue
        candidate = scan.find_candidate(str(field.get("candidate_id") or ""))
        if candidate is not None:
            field.setdefault("paragraph_text", candidate["context"])
            field.setdefault("anchor", candidate["anchor"])

    return {
        "fields": fields,
        "contract_type": str(payload.get("contract_type") or "").strip(),
        "ignored": payload.get("ignored") or [],
        "notes": str(payload.get("notes") or ""),
        "raw": raw[:8000],
    }
