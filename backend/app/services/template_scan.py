"""模板结构化扫描（P1）：把 .docx 拆成可定位的文本单元，穷举出"待填"候选。

设计前提：一份合同里"待填"的痕迹只有五类，程序能穷举，只是不知道它们的语义。
所以扫描不依赖 AI，输出的是一份**候选清单**；语义判断交给 P2 的 Dify 应用六。

| kind          | 识别方式                                          |
| ------------- | ------------------------------------------------- |
| `sdt`         | 内容控件 / 表单域（`w:sdt`、`w:fldChar` FORMTEXT） |
| `jinja`       | 已有 `{{ 变量 }}` 占位符                            |
| `blank`       | 连续下划线 / 全角空格 / 点线 / 长空白               |
| `label_empty` | `标签：` 后为空                                    |
| `empty_cell`  | 表格里带表头的空单元格                             |

每个候选都带**锚点**（`p{序号}`，按文档顺序全局编号，含表格单元格内的段落）与**字符范围**
（`start` / `end`，相对所在段落文本），回写阶段据此精确落点，不需要再解析一次文档。
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
# 占位符键必须是合法 Jinja 标识符（英文/拼音 + 下划线）
_VALID_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_KIND_SDT = "sdt"
_KIND_JINJA = "jinja"
_KIND_BLANK = "blank"
_KIND_LABEL = "label_empty"
_KIND_CELL = "empty_cell"


@dataclass
class Unit:
    """文档中的一个段落单元（含表格单元格内的段落）。"""

    anchor: str
    paragraph: Paragraph
    in_table: bool = False
    header: str = ""
    text: str = ""


@dataclass
class ScanResult:
    units: dict[str, Paragraph] = field(default_factory=dict)
    ordered: list[Unit] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    outline: str = ""

    def paragraph(self, anchor: str) -> Paragraph | None:
        return self.units.get(anchor)

    def find_candidate(self, candidate_id: str) -> dict | None:
        for item in self.candidates:
            if item["id"] == candidate_id:
                return item
        return None


def _iter_blocks(parent):
    """按文档顺序产出 Paragraph / Table，并下钻块级内容控件（w:sdt）。"""
    if isinstance(parent, DocxDocument):
        element = parent.element.body
    elif isinstance(parent, _Cell):
        element = parent._tc
    else:  # pragma: no cover - 防御性分支
        return

    for child in element.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _iter_blocks_element(content, parent)


def _iter_blocks_element(element, parent):
    for child in element.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)
        elif child.tag == qn("w:sdt"):
            content = child.find(qn("w:sdtContent"))
            if content is not None:
                yield from _iter_blocks_element(content, parent)


def _table_headers(table: Table) -> list[str]:
    """首行文本作为列头，供 empty_cell 判断与 AI 理解语义。"""
    if not table.rows:
        return []
    return [cell.text.strip() for cell in table.rows[0].cells]


def _collect_units(doc) -> list[Unit]:
    units: list[Unit] = []
    counter = 0

    def add(paragraph: Paragraph, in_table: bool, header: str) -> None:
        nonlocal counter
        units.append(
            Unit(
                anchor=f"p{counter}",
                paragraph=paragraph,
                in_table=in_table,
                header=header,
                text=paragraph.text,
            )
        )
        counter += 1

    for block in _iter_blocks(doc):
        if isinstance(block, Paragraph):
            add(block, False, "")
            continue
        headers = _table_headers(block)
        for row in block.rows:
            cells = row.cells
            for column, cell in enumerate(cells):
                header = headers[column] if column < len(headers) else ""
                for paragraph in cell.paragraphs:
                    add(paragraph, True, header)
    return units


def _has_content_control(paragraph: Paragraph) -> bool:
    """段落内是否含内容控件或表单域（作者显式标记的可填位置）。"""
    for _ in paragraph._p.iter(qn("w:sdt")):
        return True
    for instr in paragraph._p.iter(qn("w:instrText")):
        if (instr.text or "").upper().find("FORMTEXT") >= 0:
            return True
    return False


def _detect_candidates(unit: Unit, before: str, after: str) -> list[dict]:
    text = unit.text
    found: list[dict] = []

    def push(kind: str, snippet: str, start: int, end: int) -> None:
        found.append(
            {
                "anchor": unit.anchor,
                "kind": kind,
                "text": snippet,
                "start": start,
                "end": end,
                "context": text.strip(),
                "before": before.strip(),
                "after": after.strip(),
                "header": unit.header,
            }
        )

    if _has_content_control(unit.paragraph):
        push(_KIND_SDT, text.strip(), 0, len(text))

    for match in _JINJA_RE.finditer(text):
        push(_KIND_JINJA, match.group(0), match.start(), match.end())

    for match in _BLANK_RE.finditer(text):
        # 下划线紧跟在「标签：」后时，按 label_empty 处理更贴切，避免重复候选
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
    index = 0
    while index < len(units):
        unit = units[index]
        if not unit.in_table:
            lines.append(f"[{unit.anchor}] {unit.text.strip() or '（空段落）'}")
            index += 1
            continue

        # 连续同表格的单元聚成一块，一次性列出列头，便于 AI 判断单元格语义
        end = index
        while end < len(units) and units[end].in_table:
            end += 1
        block = units[index:end]
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
            result.candidates.append(candidate)
    result.outline = _build_outline(units)
    return result


def scan_document(path: str | Path) -> ScanResult:
    """扫描 .docx，返回候选清单、文档大纲与锚点映射。"""
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
            "text": item["text"],
            "context": item["context"],
            "before": item["before"],
            "after": item["after"],
            "header": item["header"],
        }
        for item in candidates
    ]


def is_valid_key(key: str) -> bool:
    return bool(_VALID_KEY_RE.match(key or ""))


def normalize_key(raw: str, fallback: str) -> str:
    """把 AI 给出的键规整成合法 Jinja 标识符（非法字符转下划线）。"""
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", (raw or "").strip())
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"{fallback}_{cleaned}" if cleaned else fallback
    return cleaned[:60]
