"""模板回写（P1 工序 3）：把确认后的字段落回 .docx，产出标准化模板。

四条硬要求：

1. **保持格式**：占位符必须写进目标跨度里的第一个 run，并继承该 run 的 `rPr`
   （字体、下划线、字号、加粗）。直接改 run 文本会丢格式，填出来的合同排版会走样。
2. **只替换该替换的那一段**：字段跨度之外的文字（「甲方：」这类标签、条款正文）必须
   逐字不动。整段替换会把标签和正文一起删掉——一份合同里一个段落能塞进 9 个变量，
   按整段写等于把条款清空。
3. **同名变量一处填写、多处生效**：一个变量在文档里可能有多处落点（首部 + 签署信息表，
   浮动文本框的 Choice/Fallback 两份副本），全部都要写上占位符。
4. **写完自检**：占位符原样落位、域骨架与 `#...#` 不残留、段落里其余文字逐字未变、
   docxtpl 重新解析出的变量集合包含确认的字段集合。自检不过就不允许启用
   （见 docs/合同模板导入与合同生成实现思路.md 第 2.3 节）。
"""

from pathlib import Path

from docx import Document as open_document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from app.core.exceptions import BizError
from app.services import template_scan, word_generator

# 字段类型 → 供前端渲染的控件（校验用，未知类型按 text 处理）
FIELD_TYPES = {"text", "textarea", "date", "number", "select", "checkbox"}

_OWNER_WORDS = ("甲方", "乙方", "丙方", "丁方", "附件")

# 含这些元素的 run 不能碰：给它赋 `.text` 会连同图形一起清空（实测把整个浮动文本框
# ——连同里面的合同编号、签订日期两个域——整块删掉了）。
_GRAPHIC_TAGS = {"drawing", "pict", "object", "txbxContent", "AlternateContent"}


def _holds_graphic(run) -> bool:
    for node in run._r.iter():
        if isinstance(node.tag, str) and node.tag.rsplit("}", 1)[-1] in _GRAPHIC_TAGS:
            return True
    return False


def _replace_range(paragraph: Paragraph, start: int, end: int, replacement: str) -> str:
    """把段落文本的 [start, end) 替换为 replacement，返回实际使用的方式。

    跨 run 的通用做法：跨度内的第一个 run 写入"前缀 + 占位符 + 后缀"，中间被完整覆盖的
    run 清空，最后一个 run 保留尾部。这样占位符继承第一个 run 的格式，其余格式不变。

    字符位置始终按 `paragraph.runs` 的**全部** run 累加（图形 run 的文本是空串，
    不影响偏移），只在挑写入目标时跳过图形 run。
    """
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(replacement)
        return "add_run"

    if start == end:  # 纯插入
        cursor = 0
        for run in runs:
            run_start, run_end = cursor, cursor + len(run.text)
            cursor = run_end
            if run_start <= start <= run_end and run.text and not _holds_graphic(run):
                offset = start - run_start
                run.text = f"{run.text[:offset]}{replacement}{run.text[offset:]}"
                return "insert"
        # 没有能安全承载的 run（跨度落空段或落在图形上）：追加一个新的
        paragraph.add_run(replacement)
        return "append_run"

    written = False
    cursor = 0
    for run in runs:
        run_start, run_end = cursor, cursor + len(run.text)
        cursor = run_end
        if run_end <= start or run_start >= end:
            continue
        if _holds_graphic(run):
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


def _write_field(paragraph: Paragraph, candidate: dict, replacement: str) -> str:
    """写表单域：拆掉域骨架，只把域结果换成占位符。

    域结果 run 自带原来的 `rPr`，占位符沿用它的格式，所以"加粗的变量名"填出来仍是加粗。
    骨架 run（fldChar / instrText）的文本是空串，删掉不会影响段落文本的位置计算。
    """
    name = str(candidate.get("name") or "")
    for span in template_scan.field_spans(paragraph):
        if span["start"] != candidate["start"] or span["end"] != candidate["end"]:
            continue
        if name and span["name"] != name:
            continue
        for element in span["control_runs"]:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
        targets = span["result_runs"]
        if not targets:
            # 域没有结果 run（空域）：整段插入会误伤标签，按落点插入即可
            return _replace_range(paragraph, candidate["start"], candidate["end"], replacement)
        targets[0].text = replacement
        for element in targets[1:]:
            element.getparent().remove(element)
        return "field"
    raise BizError(
        message=f"表单域 {name or candidate['anchor']} 在段落里已不存在，占位符无法写入"
    )


def _write_one(scan: template_scan.ScanResult, field: dict, candidate: dict) -> str:
    paragraph = scan.paragraph(candidate["anchor"])
    if paragraph is None:
        raise BizError(message=f"字段 {field['key']} 的锚点不存在：{candidate['anchor']}")
    placeholder = f"{{{{ {field['key']} }}}}"
    if candidate["kind"] == template_scan._KIND_FORM_FIELD:
        return _write_field(paragraph, candidate, placeholder)
    return _replace_range(paragraph, candidate["start"], candidate["end"], placeholder)


# ===== 落点解析 =====


def _resolve_candidates(scan: template_scan.ScanResult, field: dict, used: set[str]) -> list[dict]:
    """定位字段的**全部**落点。

    优先槽位：`slot_id` 是一个变量的身份，同名变量（表单域重名、`#...#` 内文相同）在扫描
    阶段就被聚成同一个槽位，这里把它的候选全部取出来——"填一次、多处生效"就靠这一步。

    退回顺序：`candidate_ids` → `candidate_id` → 按 `source_name` 精确匹配 → 旧的锚点
    启发式（兼容只输出 anchor 的老应用版本，见 docs/合同模板回写占位符错位缺陷修复.md）。
    """
    picked: list[dict] = []
    picked_ids: set[str] = set()

    def take(candidate_id: str) -> None:
        # 同一个候选只能被取一次：candidate_ids 与 candidate_id 常常指向同一处
        # （规整后的字段两个字段都会填），不拦住就会对同一段落写两遍，把占位符写坏。
        if not candidate_id or candidate_id in used or candidate_id in picked_ids:
            return
        candidate = scan.find_candidate(candidate_id)
        if candidate is not None:
            picked.append(candidate)
            picked_ids.add(candidate_id)

    if field.get("slot_id"):
        slot = scan.find_slot(str(field["slot_id"]))
        if slot is not None:
            for candidate_id in slot.candidate_ids:
                take(candidate_id)
        if picked:
            return picked

    for candidate_id in field.get("candidate_ids") or []:
        take(str(candidate_id))
    take(str(field.get("candidate_id") or ""))
    if picked:
        return picked

    name = str(field.get("source_name") or "").strip()
    if name:
        for candidate in scan.candidates:
            if candidate["id"] in used:
                continue
            if candidate.get("name") == name:
                picked.append(candidate)
        if picked:
            return picked

    # 旧路径：只给了 anchor。同一段落有多个空位时先按标签文字匹配，否则取最后一项
    # （"标签：____" 形态下空位在标签之后）。这是启发式，不是精确定位。
    anchor = str(field.get("anchor") or "")
    siblings = [
        item for item in scan.candidates if item["anchor"] == anchor and item["id"] not in used
    ]
    if not siblings:
        return []
    if len(siblings) == 1:
        return [siblings[0]]
    label = (field.get("label") or "").strip()
    if label:
        for item in siblings:
            if label in item["context"]:
                return [item]
    return [siblings[-1]]


# ===== 自检 =====


def _expected_text(original: str, writes: list[tuple[int, int, str]]) -> str:
    """按落点从后往前替换，得到"只换了占位符、其余一字未动"的预期段落文本。"""
    text = original
    for start, end, placeholder in sorted(writes, key=lambda item: -item[0]):
        text = f"{text[:start]}{placeholder}{text[end:]}"
    return text


def _verify_residuals(
    scan: template_scan.ScanResult, applied: list[tuple[dict, dict]]
) -> list[str]:
    """自检补齐：占位符确实写进去了、该消失的痕迹消失了、没被写的地方一字未动。

    只比对变量集合会漏掉两类事故：占位符追加在下划线后面（变量齐了但填空没被替换），
    以及整段被替换（变量也齐了，但「甲方：」和条款正文都没了）。
    """
    problems: list[str] = []
    originals = {unit.anchor: unit.text for unit in scan.ordered}
    per_anchor: dict[str, list[tuple[int, int, str]]] = {}
    intended: dict[tuple[str, str], int] = {}

    for field, candidate in applied:
        paragraph = scan.paragraph(candidate["anchor"])
        if paragraph is None:
            continue
        key = field["key"]
        placeholder = f"{{{{ {key} }}}}"
        spot = (candidate["anchor"], key)
        intended[spot] = intended.get(spot, 0) + 1
        if placeholder not in paragraph.text:
            problems.append(f"{field['label']}：占位符未写入对应段落")
            continue

        kind = candidate["kind"]
        if kind in (template_scan._KIND_BLANK, template_scan._KIND_HASH):
            # blank 的原文就是填空字符（下划线/空白），hash 的原文是 `#...#` 整段；
            # label_empty 的原文是标签，本应保留
            if candidate["text"] and candidate["text"] in paragraph.text:
                label = "原填空痕迹仍残留" if kind == template_scan._KIND_BLANK else "原 #占位符 仍残留"
                problems.append(f"{field['label']}：{label}")
                continue
        if kind == template_scan._KIND_FORM_FIELD:
            name = str(candidate.get("name") or "")
            leftovers = [
                span
                for span in template_scan.field_spans(paragraph)
                if not name or span["name"] == name
            ]
            if leftovers:
                problems.append(f"{field['label']}：表单域骨架仍残留（{name}）")
                continue

        per_anchor.setdefault(candidate["anchor"], []).append(
            (candidate["start"], candidate["end"], placeholder)
        )

    for anchor, writes in per_anchor.items():
        paragraph = scan.paragraph(anchor)
        original = originals.get(anchor, "")
        if paragraph is None or not original:
            continue
        if paragraph.text != _expected_text(original, writes):
            problems.append(f"{anchor}：字段跨度之外的文字被改动了（只应替换占位符本身）")

    # 同一段落里同一个键写了不止一次，说明落点重复（实测过：candidate_ids 与
    # candidate_id 指向同一处时会把占位符写坏，而"包含占位符"这种检查看不出来）
    for (anchor, field_key), count in intended.items():
        paragraph = scan.paragraph(anchor)
        if paragraph is None:
            continue
        actual = paragraph.text.count(f"{{{{ {field_key} }}}}")
        if actual != count:
            problems.append(f"{field_key}：占位符在 {anchor} 出现 {actual} 次，预期 {count} 次")
    return problems


# ===== 字段清单规整 =====


def _disambiguate_labels(fields: list[dict]) -> list[str]:
    """保证中文标签互不重复。

    甲乙双方成对出现的字段（「联系地址」「开户银行」「账号」「单位名称」…）在原文里
    标签一模一样，直接展示会让填表人分不清哪个是甲方、哪个是乙方。所以重名时加主体
    前缀（甲方联系地址 / 乙方联系地址）；主体也区分不开时退化成带锚点的序号，
    并留一条警告让人工在复核页处理。
    """
    warnings: list[str] = []
    groups: dict[str, list[dict]] = {}
    for field in fields:
        groups.setdefault(field["label"], []).append(field)

    for label, items in groups.items():
        if len(items) < 2:
            continue
        for field in items:
            owner = str(field.get("owner") or "").strip()
            if owner and not label.startswith(owner):
                field["label"] = f"{owner}{label}"

    # 加过主体前缀后仍重名：按顺序补序号，保证前端表单里不会有两条同名标签
    seen: dict[str, int] = {}
    for field in fields:
        label = field["label"]
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            field["label"] = f"{label}（{seen[label]}）"
            warnings.append(f"标签「{label}」有多个字段重名且主体不明，已标注序号，请核对")
    return warnings


def normalize_fields(
    scan: template_scan.ScanResult, raw_fields: list[dict]
) -> tuple[list[dict], list[str]]:
    """校验并规整 AI 给出的字段清单，返回 (干净字段, 警告)。"""
    cleaned: list[dict] = []
    warnings: list[str] = []
    used_keys: set[str] = set()
    used_slots: set[str] = set()

    for index, item in enumerate(raw_fields or []):
        if not isinstance(item, dict):
            warnings.append(f"第 {index + 1} 项不是对象，已忽略")
            continue
        label = str(item.get("label") or "").strip()
        anchor = str(item.get("anchor") or "").strip()

        slot_id = str(item.get("slot_id") or "").strip()
        slot = scan.find_slot(slot_id) if slot_id else None
        if slot_id and slot is None:
            warnings.append(f"slot {slot_id} 不存在，已按锚点定位")
            slot_id = ""
        if slot_id and slot_id in used_slots:
            warnings.append(f"slot {slot_id} 被两个字段引用，已取消后一个的槽位绑定")
            slot_id = ""
        if slot_id:
            used_slots.add(slot_id)

        anchors = [str(a) for a in (item.get("anchors") or []) if str(a).strip()]
        candidate_ids = [str(c) for c in (item.get("candidate_ids") or []) if str(c).strip()]
        # 兼容只给单个 candidate_id 的老调用方（应用六早期版本、冒烟脚本）
        legacy = str(item.get("candidate_id") or "").strip()
        if not candidate_ids and legacy:
            candidate_ids = [legacy]
        if slot is not None:
            anchors = anchors or list(slot.anchors)
            candidate_ids = candidate_ids or list(slot.candidate_ids)
        if not anchors and anchor:
            anchors = [anchor]

        if not label and slot is not None and slot.label_hint:
            label = slot.label_hint
        if not label and not (anchor or anchors or slot_id):
            warnings.append(f"第 {index + 1} 项既无 label 也无落点，已忽略")
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

        valid_candidates = [cid for cid in candidate_ids if scan.find_candidate(cid) is not None]
        if len(valid_candidates) != len(candidate_ids):
            warnings.append(f"{key} 引用了不存在的候选，已丢弃")
        candidate_ids = valid_candidates
        if not candidate_ids and not slot_id and not anchors:
            warnings.append(f"{key} 没有可用落点，将按锚点追加")

        options = item.get("options")
        cleaned.append(
            {
                "key": key,
                "label": label or key,
                "type": field_type,
                "required": bool(item.get("required")),
                "default": str(item.get("default") or ""),
                "options": [str(o) for o in options] if isinstance(options, list) else [],
                "anchor": anchors[0] if anchors else anchor,
                "anchors": anchors,
                "candidate_id": candidate_ids[0] if candidate_ids else "",
                "candidate_ids": candidate_ids,
                "slot_id": slot_id,
                # 模板里的原名（FORMTEXT 域结果 / #...# 内文）：key 被改名后仍能回到文档定位
                "source_name": str(item.get("source_name") or (slot.name if slot else "")),
                "owner": str(item.get("owner") or (slot.owner_hint if slot else "")).strip(),
                "paragraph_text": str(item.get("paragraph_text") or ""),
                "confidence": float(item.get("confidence") or 0),
                "reason": str(item.get("reason") or ""),
            }
        )
    return cleaned, warnings


def rewrite_document(source: str | Path, fields: list[dict], output: str | Path) -> dict:
    """把字段写回文档，产出标准化模板并做自检。

    返回 {"applied_keys", "warnings", "missing_in_document", "extra_in_document",
    "write_modes", "label_fixes", "placeholder_count"}。
    自检失败（应有变量缺失 / 该消失的痕迹还在 / 旁文被改动）会抛 BizError，不生成可用产物。
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
    warnings.extend(_disambiguate_labels(cleaned))

    resolved: list[tuple[dict, dict]] = []
    appended: list[tuple[dict, str]] = []
    failed: list[str] = []
    used_candidates: set[str] = set()
    for field in cleaned:
        found = _resolve_candidates(scan, field, used_candidates)
        if found:
            for candidate in found:
                used_candidates.add(candidate["id"])
                resolved.append((field, candidate))
            continue
        anchor = str(field.get("anchor") or "")
        if not anchor or scan.paragraph(anchor) is None:
            failed.append(
                f"{field['key']}（{field['label']}）：缺少可用的锚点（candidate_id 与 anchor 均无效）"
            )
            continue
        appended.append((field, anchor))
    if failed:
        raise BizError(message="以下字段无法写入模板，请修正后再启用：" + "；".join(failed))

    # 一个段落里可能有多个变量（实测一份合同能在同一段塞进 9 个域），占位符长短不一，
    # 必须从后往前写：先写左边会挪动右边那些落点的字符位置。
    resolved.sort(key=lambda pair: (pair[1]["anchor"], -pair[1]["start"]))
    modes: dict[str, str] = {}
    applied: list[tuple[dict, dict]] = []
    for field, candidate in resolved:
        try:
            mode = _write_one(scan, field, candidate)
        except BizError as exc:
            failed.append(f"{field['key']}（{field['label']}）：{exc.message}")
            continue
        applied.append((field, candidate))
        previous = modes.get(field["key"])
        modes[field["key"]] = mode if previous in (None, mode) else f"{previous}+{mode}"

    # 没有候选的字段：追加到指定段落末尾（程序没扫到、由 AI 补出的位置）
    for field, anchor in appended:
        paragraph = scan.paragraph(anchor)
        if paragraph is None:
            failed.append(f"{field['key']}（{field['label']}）：锚点不存在")
            continue
        paragraph.add_run(f"{{{{ {field['key']} }}}}")
        modes[field["key"]] = "append_run"
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
        "label_fixes": [field["label"] for field in cleaned],
        "placeholder_count": len(applied) + len(appended),
        "fields": cleaned,
    }
