"""Word 生成服务：docxtpl 模板填充 + python-docx 生成。"""

from pathlib import Path

from docxtpl import DocxTemplate


def render_template(template_path: str, context: dict, output_path: str) -> str:
    """用 docxtpl 填充模板并保存到 output_path，返回生成文件路径。"""
    template = DocxTemplate(template_path)
    template.render(context)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    template.save(output_path)
    return output_path
