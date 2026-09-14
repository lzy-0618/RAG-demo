"""模板回写（P1 工序 3）：把确认后的字段落回 .docx，产出标准化模板。

两条硬要求：

1. **保持格式**：占位符必须写进目标跨度里的第一个 run，并继承该 run 的 `rPr`
   （字体、下划线、字号）。直接改 run 文本会丢格式，填出来的合同排版会走样。
2. **写完自检**：立刻用 docxtpl 重新解析标准化模板，断言"解析出的变量集合"包含
   "确认的字段集合"。这把"AI 输出可不可信"从主观判断变成可程序化验证的断言——
   自检不过就不允许启用（见 docs/合同模板导入与合同生成实现思路.md 第 2.3 节）。
"""

from pathlib import Path

from docx import Document as open_document
from docx.text.paragraph import Paragraph

from app.core.exceptions import BizError
from app.services import template_scan, word_generator

# 字段类型 → 供前端渲染的控件（校验用，未知类型按 text 处理）
FIELD_TYPES = {"text", "textarea", "date", "number", "select", "checkbox"}


def _replace_range(paragraph: Paragraph, start: int, end: int, replacement: str) -> str:
    """把段落文本的 [start, end) 替换为 replacement，返回实际使用的方式。

    跨 run 的通用做法：跨度内的第一个 run 写入"前缀 + 占位符 + 后缀"，中间被完整覆盖的
    run 清空，最后一个 run 保留尾部。这样占位符继承第一个 run 的格式，其余格式不变。
    """
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(replacement)
        return "add_run"

    cursor = 0
    if start == end:  # 纯插入
        for run in runs:
            run_start, run_end = cursor, cursor + len(run.text)
            cursor = run_end
            if run_start <= start <= run_end and run.text:
                offset = start - run_start
                run.text = f"{run.text[:offset]}{replacement}{run.text[offset:]}"
                return "insert"
        # 段落全是空 run：写进最后一个
        runs[-1].text = f"{runs[-1].text}{replacement}"
        return "append"

    written = False
    for run in runs:
        run_start, run_end = cursor, cursor + len(run.text)
        cursor = run_end
        if run_end <= start or run_start >= end:
            continue
        prefix = run.text[: max(0, start - run_start)]
        suffix = run.text[max(0, end - run_start) :] if end <= run_end else ""
        if not written:
            run.text = f"{prefix}{replacement}{suffix}"
            written = True
        else:
            run.text = f"{prefix}{suffix}"

    if not written:  # 位置超出段落实际文本（例如 AI 给的锚点与文档不符）
        raise BizError(message=f"占位符落点越界：段落文本长度 {len(paragraph.text)}，落点 {start}-{end}")
    return "replace"


def _resolve_candidate(
    scan: template_scan.ScanResult, field: dict, used: set[str]
) -> dict | None:
    """定位字段对应的候选空位。

    优先用 AI 给出的 `candidate_id`；**缺失时按 anchor 回退解析**——应用六的提示词只要求
    输出 anchor，若只认 candidate_id 会退化成"在段末追加占位符"，导致填空题变成
    `甲方（采购方）：__________{{ party_a_name }}`（原填空没被替换掉，实测踩过）。
    """
    candidate = scan.find_candidate(field.get("candidate_id") or "")
    if candidate is not None:
        return candidate

    anchor = field.get("anchor") or ""
    siblings = [
        item
        for item in scan.candidates
        if item["anchor"] == anchor and item["id"] not in used
    ]
    if not siblings:
        return None
    if len(siblings) == 1:
        return siblings[0]

    # 同一段落有多个填空：先按标签文字匹配，否则取最后一项（"标签：____" 形态下填空在标签之后）
    label = (field.get("label") or "").strip()
    if label:
        for item in siblings:
            if label in item["context"]:
                return item
    return siblings[-1]


def _apply_one(scan: template_scan.ScanResult, field: dict, used: set[str]) -> dict:
    """写入单个字段，返回 {"mode": 写入方式, "candidate": 命中的候选或 None}。"""
    key = field["key"]
    placeholder = f"{{{{ {key} }}}}"

    candidate = _resolve_candidate(scan, field, used)
    if candidate is not None:
        paragraph = scan.paragraph(candidate["anchor"])
        if paragraph is None:
            raise BizError(message=f"字段 {key} 的锚点不存在：{candidate['anchor']}")
        mode = _replace_range(paragraph, candidate["start"], candidate["end"], placeholder)
        return {"mode": mode, "candidate": candidate}

    # 没有候选（AI 补出的、程序没扫到的位置）：追加到指定段落末尾
    anchor = field.get("anchor") or ""
    paragraph = scan.paragraph(anchor)
    if paragraph is None:
        raise BizError(message=f"字段 {key} 缺少可用的锚点（candidate_id 与 anchor 均无效）")
    paragraph.add_run(placeholder)
    return {"mode": "append_run", "candidate": None}


def _verify_residuals(
    scan: template_scan.ScanResult, applied: list[tuple[dict, dict]]
) -> list[str]:
    """自检补齐：占位符确实写进去了，且原有的填空痕迹没有残留。

    只比对变量集合会漏掉"占位符追加在下划线后面"这类文档——变量齐了但填空没被替换。
    """
    problems: list[str] = []
    for field, outcome in applied:
        candidate = outcome.get("candidate")
        anchor = field.get("anchor") or (candidate or {}).get("anchor") or ""
        paragraph = scan.paragraph(anchor)
        if paragraph is None:
            continue
        text = paragraph.text
        if f"{{{{ {field['key']} }}}}" not in text:
            problems.append(f"{field['label']}：占位符未写入对应段落")
            continue
        # blank 候选的原文就是填空字符（下划线/空白）；label_empty 的原文是标签，本应保留
        if candidate and candidate["kind"] == template_scan._KIND_BLANK and candidate["text"]:
            if candidate["text"] in text:
                problems.append(f"{field['label']}：原填空痕迹仍残留在文档中")
    return problems


def normalize_fields(scan: template_scan.ScanResult, raw_fields: list[dict]) -> tuple[list[dict], list[str]]:
    """校验并规整 AI 给出的字段清单，返回 (干净字段, 警告)。"""
    cleaned: list[dict] = []
    warnings: list[str] = []
    used_keys: set[str] = set()

    for index, item in enumerate(raw_fields or []):
        if not isinstance(item, dict):
            warnings.append(f"第 {index + 1} 项不是对象，已忽略")
            continue
        label = str(item.get("label") or "").strip()
        anchor = str(item.get("anchor") or "").strip()
        if not label and not anchor:
            warnings.append(f"第 {index + 1} 项既无 label 也无 anchor，已忽略")
            continue

        key = template_scan.normalize_key(str(item.get("key") or ""), f"field{index + 1}")
        if key in used_keys:
            warnings.append(f"字段键重复：{key}（已改为 {key}_{index + 1}）")
            key = f"{key}_{index + 1}"
        used_keys.add(key)

        field_type = str(item.get("type") or "text").strip().lower()
        if field_type not in FIELD_TYPES:
            warnings.append(f"{key} 的类型 {field_type} 不支持，已按 text 处理")
            field_type = "text"

        candidate_id = str(item.get("candidate_id") or "").strip()
        if candidate_id and scan.find_candidate(candidate_id) is None:
            warnings.append(f"{key} 的候选 {candidate_id} 不存在，将按锚点追加")
            candidate_id = ""

        options = item.get("options")
        cleaned.append(
            {
                "key": key,
                "label": label or key,
                "type": field_type,
                "required": bool(item.get("required")),
                "default": str(item.get("default") or ""),
                "options": [str(o) for o in options] if isinstance(options, list) else [],
                "anchor": anchor,
                "candidate_id": candidate_id,
                "paragraph_text": str(item.get("paragraph_text") or ""),
                "confidence": float(item.get("confidence") or 0),
                "reason": str(item.get("reason") or ""),
            }
        )
    return cleaned, warnings


def rewrite_document(
    source: str | Path, fields: list[dict], output: str | Path
) -> dict:
    """把字段写回文档，产出标准化模板并做自检。

    返回 {"applied_keys", "warnings", "missing_in_document", "extra_in_document", "write_modes"}。
    自检失败（应有变量缺失）会抛 BizError，不生成可用产物。
    """
    source_path = Path(source)
    output_path = Path(output)
    if not source_path.is_file():
        raise BizError(message=f"待处理模板不存在：{source_path}")
    if not fields:
        raise BizError(message="字段清单为空，无法生成标准化模板")

    doc = open_document(str(source_path))
    scan = template_scan.scan_document_object(doc)

    cleaned, warnings = normalize_fields(scan, fields)
    modes: dict[str, str] = {}
    applied: list[tuple[dict, dict]] = []
    used_candidates: set[str] = set()
    failed: list[str] = []
    for field in cleaned:
        try:
            outcome = _apply_one(scan, field, used_candidates)
        except BizError as exc:
            failed.append(f"{field['key']}（{field['label']}）：{exc.message}")
            continue
        if outcome["candidate"] is not None:
            used_candidates.add(outcome["candidate"]["id"])
        modes[field["key"]] = outcome["mode"]
        applied.append((field, outcome))
    if failed:
        raise BizError(message="以下字段无法写入模板，请修正后再启用：" + "；".join(failed))

    residuals = _verify_residuals(scan, applied)
    if residuals:
        raise BizError(message="标准化模板自检未通过：" + "；".join(residuals))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    # 自检：重新解析标准化模板，确认字段都变成了真正的占位符
    expected = {field["key"] for field in cleaned}
    found = set(word_generator.extract_template_variables(output_path))
    missing = sorted(expected - found)
    if missing:
        raise BizError(
            message="标准化模板自检未通过，以下字段没有生成有效占位符：" + "、".join(missing)
        )
    extra = sorted(found - expected)

    return {
        "applied_keys": sorted(expected),
        "write_modes": modes,
        "warnings": warnings,
        "missing_in_document": missing,
        # 文档里本来就有、但未被确认为字段的占位符：保留但提示
        "extra_in_document": extra,
        "fields": cleaned,
    }
