"""模板结构化扫描（P1）：把 .docx 拆成可定位的文本单元，穷举出"待填"候选。

设计前提：一份合同里"待填"的痕迹只有七类，程序能穷举，只是不知道它们的语义。
所以扫描不依赖 AI，输出的是一份**候选清单**；语义判断交给 P2 的 Dify 应用六。

| kind         | 识别方式                                             |
| ------------ | ---------------------------------------------------- |
| `form_field` | Word 表单域：`fldChar` + `instrText` 含 FORMTEXT       |
| `hash`       | `#...#` 占位符（附件类模板常用，如 `致#供应商名称#：`）  |
| `sdt`        | 内容控件（`w:sdt`），整段作为一个可填位置               |
| `jinja`      | 已有 `{{ 变量 }}` 占位符                               |
| `blank`      | 连续下划线 / 全角空格 / 点线 / 长空白                    |
| `label_empty`| `标签：` 后为空                                        |
| `empty_cell` | 表格里带表头的空单元格                                  |

每个候选都带**锚点**（`p{序号}`，按文档顺序全局编号，含表格单元格与浮动文本框内的段落）
与**字符范围**（`start` / `end`，相对所在段落文本），回写阶段据此精确落点，不需要再解析
一次文档。

`form_field` / `hash` 额外带 `name`（域结果文本 / `#...#` 内文）。**同名即同一个变量**：
按 name 聚成「槽位」（`group_slots`）后再交给 AI，因此 AI 一处识别、回写多处生效，
不会因为同一变量出现两次而产出两个字段。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document as open_document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from app.core.exceptions import BizError

# 填空痕迹：下划线 / 长横线 / 短横线 / 点线 / 全角空格 / 连续半角空白
_BLANK_RE = re.compile(r"_{2,}|—{3,}|-{3,}|·{2,}|　{2,}|[ \t]{3,}")
# 「标签：」后为空（标签限 40 字内，避免把整段正文当标签）
_LABEL_EMPTY_RE = re.compile(r"^(.{1,40}?)[：:]\s*$")
_JINJA_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# 「#...#」占位符。内文限 40 字且不含换行，避免把正文里零散的两个 # 误配成一对
_HASH_RE = re.compile(r"#([^#\n]{1,40})#")
# 占位符键必须是合法 Jinja 标识符（英文/拼音 + 下划线）
_VALID_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_KIND_FORM_FIELD = "form_field"
_KIND_HASH = "hash"
_KIND_SDT = "sdt"
_KIND_JINJA = "jinja"
_KIND_BLANK = "blank"
_KIND_LABEL = "label_empty"
_KIND_CELL = "empty_cell"

# 带名字的候选（name 相同即同一变量，聚成同一槽位）
_NAMED_KINDS = {_KIND_FORM_FIELD, _KIND_HASH}

_FORMTEXT = "FORMTEXT"

# 浮动文本框被包在 mc:AlternateContent 里，Choice（wps 形状）与 Fallback（VML 形状）
# 各存一份内容相同的副本。两份都要扫描、都要回写——Word/WPS 读 Choice，LibreOffice
# （PDF 预览链路）读 Fallback，只改一份会让另一处显示旧文本。
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_MC_CHOICE = f"{{{_MC_NS}}}Choice"
_MC_FALLBACK = f"{{{_MC_NS}}}Fallback"

# 表格列头「甲方 / 乙方」这类词可直接当主体提示，用于消解中文标签重名
_OWNER_WORDS = ("甲方", "乙方")
# 往前找主体时只看这么长的尾巴，且主体词距变量不得超过 _OWNER_MAX_GAP
_OWNER_LOOKBACK = 60
_OWNER_MAX_GAP = 40


@dataclass
class Unit:
    """文档中的一个段落单元（含表格单元格内与浮动文本框内的段落）。"""

    anchor: str
    paragraph: Paragraph
    in_table: bool = False
    header: str = ""
    text: str = ""
    in_textbox: bool = False
    # 文本框回退分支（mc:Fallback）的副本：候选照出（回写两份都要改），
    # 但结构大纲里跳过，避免同一处空位在 AI 眼里出现两次
    shadow: bool = False


@dataclass
class Slot:
    """字段槽位：一个待填变量（或一个无名空位）。"""

    slot_id: str
    name: str
    kind: str
    anchors: list[str] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    header: str = ""
    label_hint: str = ""
    owner_hint: str = ""


@dataclass
class ScanResult:
    units: dict[str, Paragraph] = field(default_factory=dict)
    ordered: list[Unit] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    outline: str = ""

    def paragraph(self, anchor: str) -> Paragraph | None:
        return self.units.get(anchor)

    def find_candidate(self, candidate_id: str) -> dict | None:
        for item in self.candidates:
            if item["id"] == candidate_id:
                return item
        return None

    def find_slot(self, slot_id: str) -> Slot | None:
        for item in self.slots:
            if item.slot_id == slot_id:
                return item
        return None

    def slot_of_candidate(self, candidate_id: str) -> Slot | None:
        for item in self.slots:
            if candidate_id in item.candidate_ids:
                return item
        return None


# ===== 表单域（FORMTEXT）解析 =====


def _field_spans(paragraph: Paragraph) -> list[dict]:
    """段落里的 FORMTEXT 表单域，返回 `[{name, start, end, control_runs, result_runs}]`。

    区间是域结果文本在段落文本里的字符位置。域结果 run 与正文 run 是同一层的兄弟
    节点，所以位置能精确算出来，回写时只替换变量本身——「甲方：」这类前后文字原样保留。

    `control_runs` 是域的骨架（fldChar begin/separate/end 与 instrText），回写时要整组
    删掉；`result_runs` 是承载变量名的那一个（可能多个）run，回写时把它的文本换掉。
    """
    spans: list[dict] = []
    stack: list[dict] = []
    offset = 0

    for run in paragraph.runs:
        element = run._r
        char = element.find(qn("w:fldChar"))
        instr = element.find(qn("w:instrText"))
        text = run.text

        if char is not None:
            kind = char.get(qn("w:fldCharType"))
            if kind == "begin":
                stack.append({"instr": "", "seen": False, "start": None, "end": None,
                              "control_runs": [element], "result_runs": []})
            elif kind == "separate":
                if stack:
                    stack[-1]["seen"] = True
                    stack[-1]["control_runs"].append(element)
            elif kind == "end":
                if stack:
                    top = stack.pop()
                    top["control_runs"].append(element)
                    if _FORMTEXT in top["instr"].upper() and top["start"] is not None:
                        spans.append(top)
        elif instr is not None:
            if stack:
                stack[-1]["instr"] += instr.text or ""
                stack[-1]["control_runs"].append(element)
        elif stack and stack[-1]["seen"] and text:
            if stack[-1]["start"] is None:
                stack[-1]["start"] = offset
            stack[-1]["end"] = offset + len(text)
            stack[-1]["result_runs"].append(element)

        offset += len(text)

    for item in spans:
        item["name"] = paragraph.text[item["start"]:item["end"]].strip()
    return spans


def _own_textboxes(p_el):
    """段落自己拥有的文本框内容（`w:txbxContent`），不含嵌套文本框的。

    `iter` 会递归到任意深度，所以往上找最近的 `w:p` 祖先来判断归属，否则外层段落会
    把内层文本框的内容也算成自己的。
    """
    found = []
    for content in p_el.iter(qn("w:txbxContent")):
        owner = content.getparent()
        while owner is not None and owner.tag != qn("w:p"):
            owner = owner.getparent()
        if owner is p_el:
            found.append(content)
    return found


def _is_fallback_branch(content) -> bool:
    """文本框副本是否位于 mc:Fallback（VML）分支。"""
    node = content
    while node is not None:
        if node.tag == _MC_FALLBACK:
            return True
        if node.tag == _MC_CHOICE:
            return False
        node = node.getparent()
    return False


# ===== 文档遍历 =====


def _iter_blocks(element, parent, *, in_table, header, in_textbox, shadow):
    """按文档顺序产出 (Paragraph | Table, meta)，下钻内容控件与浮动文本框。"""
    for child in element.iterchildren():
        meta = {"in_table": in_table, "header": header, "in_textbox": in_textbox, "shadow": shadow}
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent), meta
            for content in _own_textboxes(child):
                yield from _iter_blocks(
                    content,
                    parent,
                    in_table=in_table,
                    header=header,
                    in_textbox=True,
                    shadow=shadow or _is_fallback_branch(content),
                )
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent), meta
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _iter_blocks(
                    content, parent, in_table=in_table, header=header,
                    in_textbox=in_textbox, shadow=shadow,
                )


def _row_cells(tr):
    """行内的 (单元格元素, 起始列号)。

    直接遍历 `w:tr` 的子节点：合并单元格（`w:gridSpan`）在 XML 里只有一个 `w:tc`，
    而 python-docx 的 `row.cells` 会把同一格按跨列数重复返回——那会让一个物理段落
    被编成多个锚点，同一个空位在候选清单里出现多次（实测踩过）。列号按 gridSpan 累加。
    """
    column = 0
    for tc in tr.iterchildren(qn("w:tc")):
        span = 1
        properties = tc.find(qn("w:tcPr"))
        if properties is not None:
            grid_span = properties.find(qn("w:gridSpan"))
            if grid_span is not None:
                try:
                    span = max(1, int(grid_span.get(qn("w:val"))))
                except (TypeError, ValueError):
                    span = 1
        yield tc, column
        column += span


def _header_at(headers: list[tuple[int, str]], column: int) -> str:
    """取该列所属的列头（合并单元格跨列时取最近的前一个）。"""
    label = ""
    for start, text in headers:
        if start <= column:
            label = text
        else:
            break
    return label


def _collect_table_headers(tr) -> list[tuple[int, str]]:
    headers = []
    for tc, column in _row_cells(tr):
        text = "".join(node.text or "" for node in tc.iter(qn("w:t"))).strip()
        headers.append((column, text))
    return headers


def _collect_units(doc) -> list[Unit]:
    units: list[Unit] = []
    counter = 0

    def add(paragraph: Paragraph, meta: dict) -> None:
        nonlocal counter
        units.append(
            Unit(
                anchor=f"p{counter}",
                paragraph=paragraph,
                in_table=meta["in_table"],
                header=meta["header"],
                text=paragraph.text,
                in_textbox=meta["in_textbox"],
                shadow=meta["shadow"],
            )
        )
        counter += 1

    def walk(element, parent, *, in_table, header, in_textbox, shadow) -> None:
        for block, meta in _iter_blocks(
            element, parent, in_table=in_table, header=header,
            in_textbox=in_textbox, shadow=shadow,
        ):
            if isinstance(block, Paragraph):
                add(block, meta)
                continue
            rows = list(block._tbl.iterchildren(qn("w:tr")))
            if not rows:
                continue
            headers = _collect_table_headers(rows[0])
            for tr in rows:
                for tc, column in _row_cells(tr):
                    cell_header = _header_at(headers, column) or meta["header"]
                    walk(tc, block, in_table=True, header=cell_header,
                         in_textbox=in_textbox, shadow=shadow)

    walk(doc.element.body, doc, in_table=False, header="", in_textbox=False, shadow=False)
    return units


# ===== 候选识别 =====


def _has_content_control(paragraph: Paragraph) -> bool:
    """段落是否含内容控件或表单域（作者显式标记的可填位置）。"""
    for _ in paragraph._p.iter(qn("w:sdt")):
        return True
    for instr in paragraph._p.iter(qn("w:instrText")):
        if _FORMTEXT in (instr.text or "").upper():
            return True
    return False


def _label_hint(text: str, start: int) -> str:
    """变量左侧最像「标签」的一段文字，作为 AI 判断语义的提示。"""
    before = text[:start].rstrip()
    if before.endswith(("：", ":")):
        head = before[:-1]
        match = re.search(r"([^，。；：:\n]{1,20})$", head)
        return (match.group(1) if match else head[-20:]).strip()
    return before[-20:].strip()


def _owner_hint(text: str, start: int) -> str:
    """从变量左侧文字里推断主体（甲方 / 乙方），取尾巴里最近的甲乙方。

    主体只用于**消解中文标签重名**（甲乙双方的「联系地址」「开户银行」…），所以：
    - 联络信息那种「甲方…姓名:X，微信号:Y，手机号:Z」的长枚举，主体词会被拉开 30 多个
      字符，尾巴必须留够，否则第三、四项就找不到主体；
    - 但也不能无限往前找，否则「…乙方执DTK67份，履行期限自DTK68年」会把 DTK68 误判成
      乙方。这类误判发生在同时提到甲乙双方的条款里，而那些字段的标签本来就不会重名，
      所以不影响消歧。AI 拿到的也只是**提示**，最终由提示词要求它自己判断。
    """
    tail = text[:start][-_OWNER_LOOKBACK:]
    best_at = -1
    best_word = ""
    for word in _OWNER_WORDS:
        at = tail.rfind(word)
        if at > best_at:
            best_at = at
            best_word = word
    if best_at < 0 or len(tail) - best_at > _OWNER_MAX_GAP:
        return ""
    return best_word


def _detect_candidates(unit: Unit, before: str, after: str) -> list[dict]:
    text = unit.text
    found: list[dict] = []

    def push(kind: str, snippet: str, start: int, end: int, name: str = "") -> None:
        found.append(
            {
                "anchor": unit.anchor,
                "kind": kind,
                "text": snippet,
                "start": start,
                "end": end,
                "name": name,
                # 提示按**未 strip 的原文**计算：start 就是相对它的偏移，用 strip 过的
                # 文本会整体错位（前导空白一多，标签提示就取到隔壁字段去了）
                "label_hint": _label_hint(text, start),
                "owner_hint": _owner_hint(text, start),
                "context": text.strip(),
                "before": before.strip(),
                "after": after.strip(),
                "header": unit.header,
            }
        )

    fields = _field_spans(unit.paragraph)
    for item in fields:
        push(
            _KIND_FORM_FIELD,
            item["name"],
            item["start"],
            item["end"],
            name=item["name"],
        )

    # 内容控件兜底：整段作为一个可填位置。只在段落本身有可见文字时出候选——
    # 段落文本为空说明可填位置其实在嵌套的文本框里（由文本框自己的段落负责），
    # 这里再出一个零跨度候选只会变成"整段替换"的误伤（实测把文本框整段删掉）。
    if not fields and _has_content_control(unit.paragraph) and text.strip():
        push(_KIND_SDT, text.strip(), 0, len(text))

    for match in _JINJA_RE.finditer(text):
        push(_KIND_JINJA, match.group(0), match.start(), match.end())

    for match in _HASH_RE.finditer(text):
        push(_KIND_HASH, match.group(0), match.start(), match.end(), name=match.group(1).strip())

    # 已经被具名占位符（表单域 / #...#）覆盖或紧邻的空白不算填空：那是占位符自己的
    # 内容（`#   年月日至年月日#` 里的空格）或它的尾部留白（`开户银行：X     `），
    # 再出一个 blank 候选只会让 AI 多识别一个并不存在的字段。
    named = [(item["start"], item["end"]) for item in found if item["kind"] in _NAMED_KINDS]
    for match in _BLANK_RE.finditer(text):
        if any(match.start() <= end and match.end() >= start for start, end in named):
            continue
        push(_KIND_BLANK, match.group(0), match.start(), match.end())

    stripped = text.strip()
    if stripped:
        # 「标签：」后为空。若该段落末尾已经被 blank / jinja 候选覆盖，就不再重复出候选——
        # 否则同一处填空会变成两个候选，回写时锚点会互相踩（实测踩过）。
        tail_start = len(text.rstrip())
        covered = any(item["end"] >= tail_start and item["start"] <= len(text) for item in found)
        label = _LABEL_EMPTY_RE.match(stripped)
        if label and not covered:
            offset = len(text) - len(text.lstrip()) + len(stripped)
            push(_KIND_LABEL, label.group(1).strip(), offset, offset)

    if unit.in_table and not stripped and unit.header:
        push(_KIND_CELL, "", 0, len(text))

    return found


def _build_outline(units: list[Unit]) -> str:
    """带锚点的文档结构文本，作为 AI 通读全文的输入。"""
    lines: list[str] = []
    visible = [unit for unit in units if not unit.shadow]
    index = 0
    while index < len(visible):
        unit = visible[index]
        if not unit.in_table:
            lines.append(f"[{unit.anchor}] {unit.text.strip() or '（空段落）'}")
            index += 1
            continue

        # 连续同表格的单元聚成一块，一次性列出列头，便于 AI 判断单元格语义
        end = index
        while end < len(visible) and visible[end].in_table:
            end += 1
        block = visible[index:end]
        headers: list[str] = []
        for item in block:
            if item.header and item.header not in headers:
                headers.append(item.header)
        lines.append(f"--- 表格开始（列头：{' | '.join(headers) or '无'}）---")
        for item in block:
            label = f"「{item.header}」" if item.header else ""
            lines.append(f"  [{item.anchor}]{label} {item.text.strip() or '（空单元格）'}")
        lines.append("--- 表格结束 ---")
        index = end
    return "\n".join(lines)


def group_slots(candidates: list[dict]) -> list[Slot]:
    """把候选聚成字段槽位。

    带 name 的候选（表单域 / `#...#`）按 name 合并：**同名即同一个变量**，出现多次
    只是一个变量在文档里有多处落点，回写时一处填写、多处生效。其余类型（下划线填空、
    空标签、空单元格）本来就没有名字，一个候选就是一个槽位。
    """
    by_name: dict[str, Slot] = {}
    slots: list[Slot] = []

    for candidate in candidates:
        name = str(candidate.get("name") or "").strip()
        kind = candidate["kind"]
        owner = _owner_word(candidate) or candidate.get("owner_hint") or ""
        hint = candidate.get("label_hint") or ""
        if kind in _NAMED_KINDS and name:
            slot = by_name.get(f"{kind}:{name}")
            if slot is None:
                slot = Slot(
                    slot_id=f"s{len(slots)}",
                    name=name,
                    kind=kind,
                    label_hint=hint,
                    owner_hint=owner,
                )
                by_name[f"{kind}:{name}"] = slot
                slots.append(slot)
            slot.anchors.append(candidate["anchor"])
            slot.candidate_ids.append(candidate["id"])
            if candidate["context"] not in slot.contexts:
                slot.contexts.append(candidate["context"])
            continue

        slots.append(
            Slot(
                slot_id=f"s{len(slots)}",
                name="",
                kind=kind,
                anchors=[candidate["anchor"]],
                candidate_ids=[candidate["id"]],
                contexts=[candidate["context"]],
                header=candidate.get("header") or "",
                label_hint=hint,
                owner_hint=owner,
            )
        )
    return slots


def _owner_word(candidate: dict) -> str:
    """列头直接写了「甲方 / 乙方」时，它比正文推断更可靠（签署信息表列头就是这种）。"""
    header = (candidate.get("header") or "").strip()
    for word in _OWNER_WORDS:
        if word in header:
            return word
    return ""


def scan_document_object(doc) -> ScanResult:
    """扫描一个已打开的 python-docx 文档对象（回写阶段复用同一实例）。"""
    units = _collect_units(doc)
    if not units:
        raise BizError(message="文档为空，未解析到任何段落")

    result = ScanResult(units={unit.anchor: unit.paragraph for unit in units}, ordered=units)
    for index, unit in enumerate(units):
        before = units[index - 1].text if index > 0 else ""
        after = units[index + 1].text if index + 1 < len(units) else ""
        for candidate in _detect_candidates(unit, before, after):
            candidate["id"] = f"c{len(result.candidates)}"
            candidate["shadow"] = unit.shadow
            result.candidates.append(candidate)
    result.slots = group_slots(result.candidates)
    result.outline = _build_outline(units)
    return result


def scan_document(path: str | Path) -> ScanResult:
    """扫描 .docx，返回候选清单、槽位、文档大纲与锚点映射。"""
    target = Path(path)
    if not target.is_file():
        raise BizError(message=f"待扫描文件不存在：{target}")
    if target.suffix.lower() != ".docx":
        raise BizError(message="仅支持 .docx 模板")
    return scan_document_object(open_document(str(target)))


def candidates_for_ai(candidates: list[dict]) -> list[dict]:
    """给 AI 的候选清单：只保留语义判断需要的信息（去掉回写用的 start/end）。"""
    return [
        {
            "id": item["id"],
            "anchor": item["anchor"],
            "kind": item["kind"],
            "name": item.get("name") or "",
            "text": item["text"],
            "context": item["context"],
            "before": item["before"],
            "after": item["after"],
            "header": item["header"],
        }
        for item in candidates
    ]


def slots_for_ai(slots: list[Slot]) -> list[dict]:
    """给 AI 的槽位清单：一个槽位一个待填变量，AI 只需判语义，不必自己去重。"""
    return [
        {
            "slot_id": slot.slot_id,
            "kind": slot.kind,
            "name": slot.name,
            "label_hint": slot.label_hint,
            "owner_hint": slot.owner_hint,
            "header": slot.header,
            "occurrences": len(slot.candidate_ids),
            "contexts": slot.contexts[:3],
        }
        for slot in slots
    ]


def field_spans(paragraph: Paragraph) -> list[dict]:
    """段落里的 FORMTEXT 表单域。

    回写阶段用它拆掉域的骨架（fldChar / instrText），只保留承载变量名的那个 run——
    占位符必须替换掉整个域，否则文档里会留下一个"域结果为 `{{ x }}`"的怪东西，
    自检的"无 FORMTEXT 残留"也过不去。
    """
    return _field_spans(paragraph)


def is_valid_key(key: str) -> bool:
    return bool(_VALID_KEY_RE.match(key or ""))


def normalize_key(raw: str, fallback: str) -> str:
    """把 AI 给出的键规整成合法 Jinja 标识符（非法字符转下划线）。"""
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", (raw or "").strip())
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}" if cleaned else fallback
    return cleaned[:60]
