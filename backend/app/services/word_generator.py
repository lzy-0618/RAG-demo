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


def render_template(template_path: str, context: dict, output_path: str) -> str:
    """用 docxtpl 填充模板并保存到 output_path，返回生成文件路径。"""
    template = DocxTemplate(template_path)
    template.render(context)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    template.save(output_path)
    return output_path


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
