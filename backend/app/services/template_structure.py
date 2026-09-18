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
MAX_SLOTS = 200


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
    # 槽位才是 AI 的判断单位：同名变量（FORMEXT 域重名、#...# 内文相同）在扫描阶段就已
    # 合并，AI 一处识别、回写多处生效，不会因为同一变量出现两次而产出两个字段。
    slots = template_scan.slots_for_ai(scan.slots)
    if len(slots) > MAX_SLOTS:
        slots = slots[:MAX_SLOTS]

    outputs = await dify_client.run_template_structure(
        api_key=api_key(),
        doc_outline=scan.outline,
        candidates_json=json.dumps(candidates, ensure_ascii=False),
        slots_json=json.dumps(slots, ensure_ascii=False),
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
            "（既没有 {{ 占位符 }}，也没有表单域、下划线填空或空标签），请检查模板内容"
        )

    _bind_slots(scan, fields)

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


def _bind_slots(scan: template_scan.ScanResult, fields: list) -> None:
    """把字段绑回槽位，并补齐槽位能提供的元信息。

    应用六的提示词要求返回 `slot_id`，但**旧版应用只给 anchor**（那个版本没有槽位概念）。
    这里两种都接：能绑上槽位就补齐 `source_name` / `owner` / 全部落点，绑不上就留给回写
    阶段按锚点回退——否则用户没重新导入 Dify 应用时整条链路会直接不可用。
    """
    if not scan.slots:
        return
    by_name: dict[str, template_scan.Slot] = {}
    for slot in scan.slots:
        if slot.name:
            by_name.setdefault(slot.name, slot)

    for field in fields:
        if not isinstance(field, dict):
            continue
        slot = None
        slot_id = str(field.get("slot_id") or "").strip()
        if slot_id:
            slot = scan.find_slot(slot_id)
        if slot is None:
            # 旧应用（或模型漏填 slot_id）：用原名 / key 反查，同名即同一变量
            for probe in (field.get("source_name"), field.get("key")):
                name = str(probe or "").strip()
                if name and name in by_name:
                    slot = by_name[name]
                    break
        if slot is None:
            continue
        field["slot_id"] = slot.slot_id
        _fill(field, "source_name", slot.name)
        _fill(field, "owner", slot.owner_hint)
        _fill(field, "anchors", list(slot.anchors))
        _fill(field, "candidate_ids", list(slot.candidate_ids))


def _fill(field: dict, key: str, value) -> None:
    """字段缺该键、或该键是空值时才补。

    不能用 `setdefault`：应用六的 Code 节点会把 `anchors` / `candidate_ids` /
    `source_name` 一律输出（值可能是空数组、空串），`setdefault` 见到键已存在就什么都不做，
    槽位里的落点信息永远补不进来——字段会带着空落点往下走，复核页的"×N 落点"提示也一起失效。
    """
    if value and not field.get(key):
        field[key] = value
