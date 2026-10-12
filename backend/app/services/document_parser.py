"""制度审查的文档解析与切块；合同审查在 Dify 工作流中完成这两步。

解析链路：
- PDF：pymupdf 按页提取，天然带页码，是长文档进度与结果定位的刻度；
- docx：python-docx 按段落提取，记录段落区间；
- 纯文本：按行累积。

切块规则（设计约定）：
- 短文档（≤ 1.5 万字或 ≤ 10 页）单次审查，不切分；
- PDF 长文档按页切块，页数极多（> 50 页）时 3 页并一块，平衡调用次数与进度粒度；
- docx / 文本按字数切块（约 3500 字一块）。

扫描件等复杂法务文档的 OCR 预处理后续在此接入 unstructured/MinerU。
"""

from dataclasses import dataclass, field
from pathlib import Path

# 单次审查阈值与切块粒度
SINGLE_CHUNK_CHAR_LIMIT = 15000
SINGLE_CHUNK_PAGE_LIMIT = 10
PDF_PAGE_MERGE_THRESHOLD = 50
PDF_PAGES_PER_CHUNK = 3
# 单块字数：实测块越大，违规分析的 JSON 输出越容易超出 token 上限被截断
# （3500 字的块会出现「判定不合规但风险明细为空」），2000 字是识别率与调用次数的折中
CHARS_PER_CHUNK = 2000


@dataclass
class TextChunk:
    """一个待审查的文本块，带定位信息。"""

    text: str
    chunk_index: int
    page: int | None = None
    page_end: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    location: str = ""

    def __post_init__(self) -> None:
        if self.location:
            return
        if self.page is not None:
            self.location = (
                f"第 {self.page} 页"
                if self.page_end in (None, self.page)
                else f"第 {self.page}-{self.page_end} 页"
            )
        elif self.paragraph_start is not None:
            self.location = (
                f"第 {self.paragraph_start} 段"
                if self.paragraph_end in (None, self.paragraph_start)
                else f"第 {self.paragraph_start}-{self.paragraph_end} 段"
            )


@dataclass
class ParsedDocument:
    """解析结果：切好的块 + 统计信息。"""

    chunks: list[TextChunk] = field(default_factory=list)
    total_pages: int = 0
    char_count: int = 0


def _flush(chunks: list[TextChunk], buffer: list[str], **location: int | None) -> None:
    """把累积的段落写入一个新块（保持块序号递增）。"""
    if not buffer:
        return
    chunks.append(
        TextChunk(text="\n".join(buffer), chunk_index=len(chunks) + 1, **location)
    )


def parse_text(content: str) -> ParsedDocument:
    """纯文本输入：按行分段后按字数切块。"""
    text = (content or "").strip()
    if not text:
        return ParsedDocument()

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[TextChunk] = []
    buffer: list[str] = []
    buffer_len = 0
    para_start = 1

    for idx, para in enumerate(paragraphs, start=1):
        if buffer_len and buffer_len + len(para) > CHARS_PER_CHUNK:
            _flush(chunks, buffer, paragraph_start=para_start, paragraph_end=idx - 1)
            buffer, buffer_len = [], 0
            para_start = idx
        buffer.append(para)
        buffer_len += len(para)
    _flush(chunks, buffer, paragraph_start=para_start, paragraph_end=len(paragraphs))

    return ParsedDocument(chunks=chunks, char_count=len(text))


def parse_docx(file_path: str | Path) -> ParsedDocument:
    """docx：按段落提取文本，再按字数切块（记录段落区间）。"""
    from docx import Document as DocxDocument

    document = DocxDocument(str(file_path))
    non_empty = [
        (i, (p.text or "").strip())
        for i, p in enumerate(document.paragraphs, start=1)
        if (p.text or "").strip()
    ]
    if not non_empty:
        return ParsedDocument()

    chunks: list[TextChunk] = []
    buffer: list[str] = []
    buffer_len = 0
    para_start = non_empty[0][0]

    for idx, text in non_empty:
        if buffer_len and buffer_len + len(text) > CHARS_PER_CHUNK:
            _flush(chunks, buffer, paragraph_start=para_start, paragraph_end=idx - 1)
            buffer, buffer_len = [], 0
            para_start = idx
        buffer.append(text)
        buffer_len += len(text)
    _flush(chunks, buffer, paragraph_start=para_start, paragraph_end=non_empty[-1][0])

    return ParsedDocument(chunks=chunks, char_count=sum(len(t) for _, t in non_empty))


def parse_pdf(file_path: str | Path) -> ParsedDocument:
    """PDF：按页提取；页数很多时合并若干页为一块。"""
    try:
        import pymupdf  # 1.24+ 的新包名
    except ImportError:  # pragma: no cover - 兼容旧包名
        import fitz as pymupdf

    with pymupdf.open(str(file_path)) as doc:
        pages = [(i + 1, (page.get_text() or "").strip()) for i, page in enumerate(doc)]
        total_pages = len(pages)

    non_empty = [(num, text) for num, text in pages if text]
    if not non_empty:
        return ParsedDocument(total_pages=total_pages)

    pages_per_chunk = PDF_PAGES_PER_CHUNK if total_pages > PDF_PAGE_MERGE_THRESHOLD else 1
    chunks: list[TextChunk] = []
    buffer: list[str] = []
    page_start = non_empty[0][0]
    page_end = page_start

    for num, text in non_empty:
        if not buffer:
            page_start = num
        buffer.append(text)
        page_end = num
        if num - page_start + 1 >= pages_per_chunk:
            _flush(chunks, buffer, page=page_start, page_end=page_end)
            buffer = []
    _flush(chunks, buffer, page=page_start, page_end=page_end)

    return ParsedDocument(
        chunks=chunks,
        total_pages=total_pages,
        char_count=sum(len(t) for _, t in non_empty),
    )


def parse_file(file_path: str | Path) -> ParsedDocument:
    """按扩展名分派解析器。

    只接受已经是 OOXML 的 .docx：legacy .doc 属二进制老格式，由上传入口
    （review / knowledge 服务）统一归一化后再进来，解析层不做格式转换。
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(file_path)
    if suffix == ".docx":
        return parse_docx(file_path)
    if suffix in (".md", ".txt"):
        return parse_text(Path(file_path).read_text(encoding="utf-8", errors="ignore"))
    raise ValueError(
        f"暂不支持的文件类型：{suffix}（支持 pdf / docx / md / txt；"
        ".doc 需在上传入口归一化为 .docx）"
    )


def parse_document(file_path: str | Path) -> ParsedDocument:
    """解析文件为切好块的文档（parse_file 的语义化别名）。"""
    return parse_file(file_path)


def merge_short_document(parsed: ParsedDocument) -> ParsedDocument:
    """短文档不切分：按约定阈值合并为单块，减少无谓的多次 LLM 调用。"""
    if len(parsed.chunks) <= 1:
        return parsed
    within_chars = 0 < parsed.char_count <= SINGLE_CHUNK_CHAR_LIMIT
    within_pages = 0 < parsed.total_pages <= SINGLE_CHUNK_PAGE_LIMIT
    if not (within_chars or within_pages):
        return parsed

    first, last = parsed.chunks[0], parsed.chunks[-1]
    merged = TextChunk(
        text="\n".join(c.text for c in parsed.chunks),
        chunk_index=1,
        page=first.page,
        page_end=last.page_end,
        paragraph_start=first.paragraph_start,
        paragraph_end=last.paragraph_end,
    )
    return ParsedDocument(
        chunks=[merged], total_pages=parsed.total_pages, char_count=parsed.char_count
    )
