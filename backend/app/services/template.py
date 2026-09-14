"""合同模板库业务逻辑（需求 ⑥）与合同生成（需求 ⑦）。

模板文件单独放 `templates/` 目录（区别于知识库上传目录 uploads/ 与生成产物 outputs/）。
合同生成走 docxtpl 确定性填充；只有需要 AI 撰写条款正文时才调 Dify（本模块默认不调）。
"""

import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizError, NotFoundError
from app.models.template import ContractTemplate
from app.services import word_generator

TEMPLATE_DIR = settings.TEMPLATE_DIR
MAX_TEMPLATE_SIZE_MB = 20


def _template_dir() -> Path:
    path = Path(settings.TEMPLATE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_template_file(filename: str, content: bytes) -> Path:
    safe = Path(filename).name
    target = _template_dir() / f"{uuid.uuid4().hex}_{safe}"
    target.write_bytes(content)
    return target


def parse_variables(item: ContractTemplate) -> list[str]:
    """读取模板占位变量（优先用导入时缓存的解析结果）。"""
    if item.variables_json:
        try:
            cached = json.loads(item.variables_json)
            if isinstance(cached, list):
                return [str(v) for v in cached]
        except json.JSONDecodeError:
            pass
    return []


async def create_template(
    db: Session,
    *,
    filename: str,
    content: bytes,
    name: str | None,
    category: str | None,
    description: str | None,
    uploader: str | None,
) -> ContractTemplate:
    """导入模板：校验扩展名 → 落地 → 解析占位变量 → 落库。"""
    if not filename.lower().endswith(".docx"):
        raise BizError(message="仅支持 .docx 模板（docxtpl 需基于 Word 模板填充）")
    if not content:
        raise BizError(message="模板文件为空")
    if len(content) > MAX_TEMPLATE_SIZE_MB * 1024 * 1024:
        raise BizError(message=f"模板文件超过 {MAX_TEMPLATE_SIZE_MB}MB 限制")

    path = await asyncio.to_thread(_save_template_file, filename, content)
    variables = await asyncio.to_thread(word_generator.extract_template_variables, path)

    item = ContractTemplate(
        name=(name or Path(filename).stem).strip(),
        category=(category or "").strip() or None,
        file_name=Path(filename).name,
        file_path=str(path),
        file_size=len(content),
        variables_json=json.dumps(variables, ensure_ascii=False),
        description=description,
        uploader=uploader,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def list_templates(
    db: Session, *, category: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[ContractTemplate], int]:
    stmt = select(ContractTemplate)
    count_stmt = select(func.count()).select_from(ContractTemplate)
    if category:
        stmt = stmt.where(ContractTemplate.category == category)
        count_stmt = count_stmt.where(ContractTemplate.category == category)

    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(ContractTemplate.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(rows), total


def list_categories(db: Session) -> list[str]:
    rows = db.execute(
        select(ContractTemplate.category).where(ContractTemplate.category.is_not(None)).distinct()
    ).all()
    return sorted({row[0] for row in rows if row[0]})


def get_template(db: Session, template_id: int) -> ContractTemplate:
    item = db.get(ContractTemplate, template_id)
    if item is None:
        raise NotFoundError("模板不存在")
    return item


def delete_template(db: Session, item: ContractTemplate) -> None:
    Path(item.file_path).unlink(missing_ok=True)
    db.delete(item)
    db.commit()


def render_contract(db: Session, item: ContractTemplate, variables: dict) -> tuple[str, str]:
    """合同生成（需求⑦）：docxtpl 确定性填充，返回 (生成文件路径, 文件名)。

    缺失的占位变量补空串，避免 docxtpl 抛错中断生成；多余变量忽略。
    """
    required = parse_variables(item)
    context = {key: (variables.get(key) or "") for key in required}
    # 模板中可能含非占位符变量（如 rich text），一并带上用户提交值
    context.update({k: v for k, v in (variables or {}).items() if k not in context})

    output_dir = word_generator.ensure_output_dir(settings.OUTPUT_DIR)
    file_name = word_generator.safe_filename(item.name)
    output_path = str(output_dir / file_name)

    try:
        word_generator.render_template(item.file_path, context, output_path)
    except Exception as exc:  # noqa: BLE001 - 模板语法/变量错误要回给前端
        raise BizError(message=f"合同生成失败：{exc}") from exc

    return output_path, file_name
