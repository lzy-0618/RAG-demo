"""Word 生成服务：docxtpl 模板填充（合同）+ python-docx 程序化排版（规章制度）。"""

from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate

# 生成产物目录（与上传目录分开，便于清理与挂载对象存储）
OUTPUT_DIR = "outputs"
# 生成文件名中的非法字符
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'

# ===== 规章制度 Word 排版样式（需求⑧：标题与正文的字体/字号/加粗/颜色显式指定） =====
DOC_FONT_HEADING = "黑体"  # 章节标题中文字体
DOC_FONT_BODY = "宋体"  # 正文字体中文字体
HEADING_SIZE_PT = 15  # 章节标题字号：小三
HEADING_BOLD = True  # 章节标题加粗
BODY_SIZE_PT = 12  # 正文字号：小四
BODY_BOLD = False  # 正文不加粗
DOC_TITLE_SIZE_PT = 22  # 文档标题字号：二号（仅在显式传入 title 时使用）
DOC_FONT_COLOR = (0, 0, 0)  # 统一黑色
BODY_FIRST_LINE_INDENT_PT = 24  # 正文首行缩进 2 字符
LINE_SPACING = 1.5  # 行距


def ensure_output_dir(output_dir: str = OUTPUT_DIR) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str, suffix: str = ".docx") -> str:
    """清理文件名中的非法字符，并追加时间戳避免覆盖。"""
    cleaned = "".join(ch for ch in (name or "").strip() if ch not in _INVALID_FILENAME_CHARS)
    cleaned = cleaned.replace(" ", "_") or "document"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{cleaned[:80]}_{stamp}{suffix}"


def extract_template_variables(template_path: str | Path) -> list[str]:
    """解析模板中的占位变量（docxtpl 未声明变量），供前端渲染填报表单。"""
    template = DocxTemplate(str(template_path))
    try:
        variables = template.get_undeclared_template_variables()
    except Exception:  # noqa: BLE001 - 模板语法异常时不让导入失败，返回空列表由人工检查
        return []
    return sorted(str(v) for v in variables)


def render_template(
    template_path: str, context: dict, output_path: str, *, normalize: bool = True
) -> str:
    """用 docxtpl 填充模板并保存到 output_path，返回生成文件路径。

    normalize=True 时对产物做排版规范化（见 normalize_docx_typography）。
    """
    template = DocxTemplate(template_path)
    template.render(context)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    template.save(output_path)
    if normalize:
        normalize_docx_typography(output_path)
    return output_path


# ===== 合同 Word 排版规范化（需求⑦）=====
# 合同模板决定版式，因此这里只补「缺失的那一半」：把没有显式声明的字体补出来，
# 已指定的字体/字号/加粗一律保留 —— 覆盖会破坏模板自己的版式设计。
#
# 为什么必须补字体：模板改写环节（template_rewrite）会程序化生成占位 run，
# 这些 run 往往只有西文字体甚至完全没有 rFonts，中文字符就会回退到
# Office 中文默认字体（等线），和模板其余部分明显不一致。
CONTRACT_FONT_BODY = "宋体"  # 中文字体缺失时的兜底（不跟随西文字体，见下）
CONTRACT_BODY_SIZE_PT = 12  # Normal 样式未声明字号时补入：小四
CONTRACT_TITLE_BOLD = True  # 首段（合同标题）未声明加粗时补加粗
CONTRACT_TITLE_MAX_CHARS = 40  # 首段短于该字数才按标题处理
CONTRACT_TITLE_SIZE_PT: float | None = None  # 设为数值则强制标题字号；None = 保留模板
CONTRACT_FORCE_FONT = False  # True = 全文字体统一覆盖（会放弃模板的字体搭配）


def _iter_paragraphs(container):
    """容器的段落，以及其中表格（含嵌套）内的段落。"""
    for paragraph in list(getattr(container, "paragraphs", []) or []):
        yield paragraph
    for table in list(getattr(container, "tables", []) or []):
        for row in table.rows:
            for cell in row.cells:
                yield from _iter_paragraphs(cell)


def _rpr_fonts(rpr):
    """取 rPr 下的 rFonts，没有则按 schema 顺序插入。

    rPr 的子元素有次序要求：rFonts 必须排在 rStyle 之后、其余属性之前。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is not None:
        return rfonts
    rfonts = OxmlElement("w:rFonts")
    first = rpr[0] if len(rpr) else None
    if first is not None and first.tag == qn("w:rStyle"):
        first.addnext(rfonts)
    else:
        rpr.insert(0, rfonts)
    return rfonts


def _fill_fonts(rfonts, font_name: str, *, force: bool = False) -> None:
    """补齐 rFonts 缺少的字体属性；force=False 时不动已有值。

    属性级补齐即可解决主题回退：Word 中文模板通常只写 eastAsiaTheme="minorEastAsia"
    （解析为等线），并没有 w:eastAsia 属性，所以补上显式属性就能覆盖主题值。
    """
    from docx.oxml.ns import qn

    latin = rfonts.get(qn("w:ascii")) or rfonts.get(qn("w:hAnsi"))
    for attr in ("w:ascii", "w:hAnsi"):
        if force or rfonts.get(qn(attr)) is None:
            rfonts.set(qn(attr), latin or font_name)
    # 中文字体不跟随西文字体：模板里 ascii 常是 Times New Roman 这类纯西文字体，
    # 中文用它等于没设，仍会二次回退。
    for attr in ("w:eastAsia", "w:cs"):
        if force or rfonts.get(qn(attr)) is None:
            rfonts.set(qn(attr), font_name)


def _ensure_run_font(run, font_name: str, *, force: bool = False) -> None:
    """补齐单个 run 的字体属性。"""
    _fill_fonts(_rpr_fonts(run._element.get_or_add_rPr()), font_name, force=force)


def _apply_document_default_font(document, font_name: str) -> None:
    """补齐文档默认字体。

    这一步是根本：凡是「未显式指定」的文字都从这里取值，不补则中文落到主题字体。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    styles_el = document.styles.element
    doc_defaults = styles_el.find(qn("w:docDefaults"))
    if doc_defaults is None:
        doc_defaults = OxmlElement("w:docDefaults")
        styles_el.insert(0, doc_defaults)
    rpr_default = doc_defaults.find(qn("w:rPrDefault"))
    if rpr_default is None:
        rpr_default = OxmlElement("w:rPrDefault")
        doc_defaults.insert(0, rpr_default)
    rpr = rpr_default.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        rpr_default.append(rpr)
    _fill_fonts(_rpr_fonts(rpr), font_name)


def _apply_normal_style(document, font_name: str, size_pt: float) -> None:
    """Normal 样式：补中文字体，未声明字号时补小四。"""
    from docx.shared import Pt

    try:
        normal = document.styles["Normal"]
    except KeyError:  # noqa: BLE001 - 极少数 docx 没有 Normal 样式，跳过即可
        return
    _fill_fonts(_rpr_fonts(normal.element.get_or_add_rPr()), font_name)
    if normal.font.size is None:
        normal.font.size = Pt(size_pt)


def normalize_docx_typography(path: str) -> None:
    """规范化已生成的 .docx：默认字体、缺失字体、标题加粗。

    只做「补齐」不做「统一」，因此可用于任何模板，不会破坏模板原有的字体搭配。
    """
    from docx import Document as DocxDocument

    document = DocxDocument(path)
    _apply_document_default_font(document, CONTRACT_FONT_BODY)
    _apply_normal_style(document, CONTRACT_FONT_BODY, CONTRACT_BODY_SIZE_PT)

    containers = [document]
    for section in document.sections:
        # is_linked_to_previous 为真时页眉页脚是继承来的，访问会凭空创建部件
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            if not part.is_linked_to_previous:
                containers.append(part)

    for container in containers:
        for paragraph in _iter_paragraphs(container):
            for run in paragraph.runs:
                _ensure_run_font(run, CONTRACT_FONT_BODY, force=CONTRACT_FORCE_FONT)

    if CONTRACT_TITLE_BOLD or CONTRACT_TITLE_SIZE_PT:
        _apply_title_style(document)

    document.save(path)


def _apply_title_style(document) -> None:
    """首段按合同标题处理：未声明加粗时补加粗，可选补字号。"""
    from docx.shared import Pt

    first = next((p for p in document.paragraphs if p.text.strip()), None)
    if first is None or len(first.text.strip()) > CONTRACT_TITLE_MAX_CHARS:
        return
    for run in first.runs:
        if CONTRACT_TITLE_BOLD and run.font.bold is None:
            run.font.bold = True
        if CONTRACT_TITLE_SIZE_PT and run.font.size is None:
            run.font.size = Pt(CONTRACT_TITLE_SIZE_PT)


def _apply_run_style(run, *, font_name: str, size_pt: float, bold: bool) -> None:
    """设置 run 的字体/字号/加粗/颜色，并显式设置中文字体（eastAsia），避免 Word 回退字体。"""
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(*DOC_FONT_COLOR)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        from docx.oxml import OxmlElement

        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), font_name)
    rfonts.set(qn("w:ascii"), font_name)
    rfonts.set(qn("w:hAnsi"), font_name)


def build_docx_from_sections(
    sections: list[dict],
    output_path: str,
    title: str | None = None,
    subtitle: str | None = None,
) -> str:
    """用 python-docx 把章节结构排版成 .docx（需求⑧，无固定模板）。

    sections 形如 [{"title": "第一章 总则", "content": "第一条 ..."}]。
    文档**只包含规章制度正文本身**（章节标题 + 条款），不写入用户的生成提示词；
    title/subtitle 仅在调用方明确需要时使用。
    标题与正文的字体、字号、加粗、颜色由文件顶部常量统一控制。
    """
    from docx import Document as DocxDocument
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = DocxDocument()

    # 默认样式（Normal）也设为宋体小四黑色，未显式设置的段落不会走 Word 默认字体
    normal = document.styles["Normal"]
    normal.font.size = Pt(BODY_SIZE_PT)
    normal.font.bold = BODY_BOLD
    try:
        normal.font.name = DOC_FONT_BODY
        from docx.oxml.ns import qn

        normal.element.rPr.rFonts.set(qn("w:eastAsia"), DOC_FONT_BODY)
    except Exception:  # noqa: BLE001 - 样式细节失败不影响正文生成
        pass

    if title:
        para = document.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _apply_run_style(
            para.add_run(title), font_name=DOC_FONT_HEADING, size_pt=DOC_TITLE_SIZE_PT, bold=True
        )
    if subtitle:
        para = document.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _apply_run_style(
            para.add_run(subtitle), font_name=DOC_FONT_BODY, size_pt=BODY_SIZE_PT, bold=False
        )

    for section in sections or []:
        section_title = str(section.get("title") or "").strip()
        content = str(section.get("content") or "").strip()

        if section_title:
            heading = document.add_paragraph()
            heading.paragraph_format.space_before = Pt(12)
            heading.paragraph_format.space_after = Pt(6)
            heading.paragraph_format.line_spacing = LINE_SPACING
            _apply_run_style(
                heading.add_run(section_title),
                font_name=DOC_FONT_HEADING,
                size_pt=HEADING_SIZE_PT,
                bold=HEADING_BOLD,
            )

        # 正文按换行拆段，首行缩进两字符、1.5 倍行距
        for line in [seg.strip() for seg in content.split("\n") if seg.strip()]:
            para = document.add_paragraph()
            para.paragraph_format.first_line_indent = Pt(BODY_FIRST_LINE_INDENT_PT)
            para.paragraph_format.line_spacing = LINE_SPACING
            _apply_run_style(
                para.add_run(line),
                font_name=DOC_FONT_BODY,
                size_pt=BODY_SIZE_PT,
                bold=BODY_BOLD,
            )

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(target))
    return str(target)
