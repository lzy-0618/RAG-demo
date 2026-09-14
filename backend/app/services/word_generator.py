"""Word 生成服务：docxtpl 模板填充（合同）+ python-docx 程序化排版（规章制度）。"""

from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate

# 生成产物目录（与上传目录分开，便于清理与挂载对象存储）
OUTPUT_DIR = "outputs"
# 生成文件名中的非法字符
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


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


def build_docx_from_sections(
    sections: list[dict],
    output_path: str,
    title: str | None = None,
    subtitle: str | None = None,
) -> str:
    """用 python-docx 把章节结构排版成 .docx（需求⑧，无固定模板）。

    sections 形如 [{"title": "第一章 总则", "content": "第一条 ..."}]；
    章节标题用 Heading 2、正文按段落写入，标题与正文之间保持审阅友好的间距。
    """
    from docx import Document as DocxDocument
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = DocxDocument()

    if title:
        heading = document.add_heading(title, level=0)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if subtitle:
        para = document.add_paragraph(subtitle)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.runs[0].font.size = Pt(10.5)

    for section in sections or []:
        section_title = str(section.get("title") or "").strip()
        content = str(section.get("content") or "").strip()
        if section_title:
            document.add_heading(section_title, level=2)
        # 正文按空行/换行拆段，保持条款层级
        for line in [seg.strip() for seg in content.split("\n") if seg.strip()]:
            document.add_paragraph(line)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(target))
    return str(target)
