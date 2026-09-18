"""合同模板库业务逻辑（需求 ⑥）与合同生成（需求 ⑦）。

模板的形态分两份文件，`source_path`（用户上传的原始文件）永远保留：

- 结构化（P1/P2）：扫描 → AI 识别字段 → 回写产出**标准化模板**（占位符规范化为 `{{ key }}`）；
- 生成（需求⑦）：对标准化模板做 docxtpl 确定性填充，不调用大模型。

识别结果**不直接生效**：落到 `review`（待复核），人工在复核页确认后才变 `ready` 并出现在生成页。
"""

import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import BizError, NotFoundError
from app.models.template import (
    STRUCTURE_FAILED,
    STRUCTURE_PENDING,
    STRUCTURE_READY,
    STRUCTURE_REVIEW,
    STRUCTURE_STRUCTURING,
    ContractTemplate,
    TemplateCategory,
)
from app.services import docx_convert
from app.services import template_rewrite, template_scan, word_generator
from app.services import template_structure

TEMPLATE_DIR = settings.TEMPLATE_DIR
MAX_TEMPLATE_SIZE_MB = 20
# .doc 是老格式但在实际资料里很常见，导入时统一归一化为 .docx 后落库
_ALLOWED_TEMPLATE_SUFFIXES = {".doc", ".docx"}


def _template_dir() -> Path:
    path = Path(settings.TEMPLATE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_template_file(filename: str, content: bytes) -> Path:
    safe = Path(filename).name
    target = _template_dir() / f"{uuid.uuid4().hex}_{safe}"
    target.write_bytes(content)
    return target


# ===== 字段 schema =====


def parse_fields(item: ContractTemplate) -> list[dict]:
    """模板的字段 schema（结构化后的结果）。"""
    if not item.fields_json:
        return []
    try:
        data = json.loads(item.fields_json)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def parse_meta(item: ContractTemplate) -> dict:
    if not item.structure_meta_json:
        return {}
    try:
        data = json.loads(item.structure_meta_json)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def parse_variables(item: ContractTemplate) -> list[str]:
    """标准化模板的占位变量（优先用复核确认的结果）。"""
    fields = parse_fields(item)
    if fields:
        return [str(field["key"]) for field in fields]
    if item.variables_json:
        try:
            cached = json.loads(item.variables_json)
            if isinstance(cached, list):
                return [str(v) for v in cached]
        except json.JSONDecodeError:
            pass
    return []


def working_path(item: ContractTemplate) -> str:
    """生成阶段使用的文件：有标准化模板就用它，否则回退原始文件。"""
    return item.standardized_path or item.file_path


# ===== 模板 CRUD =====


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
    """导入模板：校验 → 落地为原始文件 → 落库（状态 pending，等结构化）。

    legacy .doc 先归一化为 .docx：扫描（template_scan）与回写（template_rewrite）都基于
    python-docx，只认 OOXML，所以归一化必须发生在落库之前，source_path 落的是 .docx。
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix not in _ALLOWED_TEMPLATE_SUFFIXES:
        raise BizError(message="仅支持 .doc / .docx 模板")
    if not content:
        raise BizError(message="模板文件为空")
    if len(content) > MAX_TEMPLATE_SIZE_MB * 1024 * 1024:
        raise BizError(message=f"模板文件超过 {MAX_TEMPLATE_SIZE_MB}MB 限制")

    path = await asyncio.to_thread(_save_template_file, filename, content)
    if docx_convert.is_legacy_doc(path):
        original = path
        try:
            path = await docx_convert.convert_legacy_doc(original, original.parent)
        finally:
            # 原始 .doc 不再被 file_path / source_path 引用，留着就是删除模板时清不掉的孤儿
            original.unlink(missing_ok=True)
    # 落盘与下载都按实际存储的 .docx 命名，避免下载出 .doc 后缀的 docx 内容
    stored_name = f"{Path(filename).stem}.docx"
    variables = await asyncio.to_thread(word_generator.extract_template_variables, path)

    item = ContractTemplate(
        name=(name or Path(filename).stem).strip(),
        category=(category or "").strip() or None,
        file_name=stored_name,
        file_path=str(path),
        source_path=str(path),
        file_size=path.stat().st_size,
        variables_json=json.dumps(variables, ensure_ascii=False),
        description=description,
        uploader=uploader,
        structure_status=STRUCTURE_PENDING,
        version=1,
    )
    db.add(item)
    if item.category:
        ensure_category(db, item.category)
    db.commit()
    db.refresh(item)
    return item


def list_templates(
    db: Session, *, category: str | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[ContractTemplate], int]:
    stmt = select(ContractTemplate).where(ContractTemplate.deleted_at.is_(None))
    count_stmt = (
        select(func.count()).select_from(ContractTemplate).where(ContractTemplate.deleted_at.is_(None))
    )
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


def get_template(db: Session, template_id: int) -> ContractTemplate:
    item = db.get(ContractTemplate, template_id)
    if item is None or item.deleted_at is not None:
        raise NotFoundError("模板不存在")
    return item


def update_template_meta(
    db: Session,
    item: ContractTemplate,
    *,
    name: str | None,
    category: str | None,
    description: str | None,
) -> ContractTemplate:
    if name is not None:
        item.name = name
    if category is not None:
        item.category = category or None
        if item.category:
            ensure_category(db, item.category)
    if description is not None:
        item.description = description
    db.commit()
    db.refresh(item)
    return item


def delete_template(db: Session, item: ContractTemplate) -> None:
    """软删除：保留文件与记录，避免误删后无法恢复，也让生成历史仍可读。"""
    from datetime import datetime

    item.deleted_at = datetime.now()
    db.commit()


# ===== 结构化（P2）=====


def _structure_file_path(item: ContractTemplate) -> Path:
    """标准化模板的稳定路径（同一模板重复结构化会覆盖，不留垃圾文件）。"""
    return _template_dir() / f"{item.id}_standardized.docx"


def _set_structure(db: Session, item: ContractTemplate, status: str, **extra) -> None:
    for key, value in extra.items():
        setattr(item, key, value)
    item.structure_status = status
    db.commit()
    db.refresh(item)


async def structure_template(db: Session, item: ContractTemplate, user: str) -> dict:
    """扫描 → AI 识别 → 回写 → 落库（状态 review，需人工复核后才启用）。"""
    source = Path(item.source_path or item.file_path)
    if not source.is_file():
        raise NotFoundError("模板原文件不存在，请重新导入")

    _set_structure(db, item, STRUCTURE_STRUCTURING, structure_meta_json=None)
    try:
        scan = await asyncio.to_thread(template_scan.scan_document, source)
        identified = await template_structure.identify_fields(scan, item.name, user)
        output = _structure_file_path(item)
        result = await asyncio.to_thread(
            template_rewrite.rewrite_document, source, identified["fields"], output
        )
    except Exception as exc:  # noqa: BLE001 - 失败原因要落库，供复核页展示
        message = exc.message if isinstance(exc, BizError) else str(exc)
        _set_structure(
            db,
            item,
            STRUCTURE_FAILED,
            structure_meta_json=json.dumps({"error": message[:1000]}, ensure_ascii=False),
        )
        raise

    meta = {
        "candidate_count": len(scan.candidates),
        "candidate_kinds": sorted({item_["kind"] for item_ in scan.candidates}),
        "slot_count": len(scan.slots),
        "named_slot_count": sum(1 for slot in scan.slots if slot.name),
        "placeholder_count": result.get("placeholder_count"),
        "contract_type": identified["contract_type"],
        "ignored": identified["ignored"],
        "notes": identified["notes"],
        "warnings": result["warnings"],
        "write_modes": result["write_modes"],
        "extra_in_document": result["extra_in_document"],
        "raw_output": identified["raw"],
    }
    _set_structure(
        db,
        item,
        STRUCTURE_REVIEW,
        standardized_path=str(output),
        fields_json=json.dumps(result["fields"], ensure_ascii=False),
        variables_json=json.dumps(
            sorted(set(result["applied_keys"]) | set(result["extra_in_document"])),
            ensure_ascii=False,
        ),
        structure_meta_json=json.dumps(meta, ensure_ascii=False),
    )
    if identified["contract_type"] and not item.category:
        update_template_meta(db, item, name=None, category=identified["contract_type"], description=None)
    return {"status": item.structure_status, "fields": result["fields"], "meta": meta}


def save_fields(
    db: Session,
    item: ContractTemplate,
    *,
    fields: list[dict],
    contract_type: str | None,
    enable: bool,
) -> dict:
    """保存复核结果：重新回写标准化模板（含自检），确认后置为 ready。"""
    source = Path(item.source_path or item.file_path)
    if not source.is_file():
        raise NotFoundError("模板原文件不存在，请重新导入")

    output = _structure_file_path(item)
    result = template_rewrite.rewrite_document(source, fields, output)

    item.standardized_path = str(output)
    item.fields_json = json.dumps(result["fields"], ensure_ascii=False)
    item.variables_json = json.dumps(
        sorted(set(result["applied_keys"]) | set(result["extra_in_document"])), ensure_ascii=False
    )
    item.version = (item.version or 1) + 1
    if contract_type:
        item.category = contract_type
        ensure_category(db, contract_type)
    item.structure_status = STRUCTURE_READY if enable else STRUCTURE_REVIEW
    db.commit()
    db.refresh(item)
    return {"status": item.structure_status, "fields": result["fields"], "warnings": result["warnings"]}


def reset_structure(db: Session, item: ContractTemplate) -> None:
    """回到待识别状态（换模板文件或想重跑识别时用）。"""
    _set_structure(db, item, STRUCTURE_PENDING, structure_meta_json=None)


# ===== 合同类型受控词表 =====


def list_categories(db: Session) -> list[str]:
    rows = db.execute(
        select(TemplateCategory.name)
        .where(TemplateCategory.enabled.is_(True))
        .order_by(TemplateCategory.sort_order, TemplateCategory.name)
    ).all()
    return [row[0] for row in rows]


def ensure_category(db: Session, name: str) -> TemplateCategory:
    """按名称取词条，不存在则补建（导入模板时自动登记，避免分类流失）。"""
    cleaned = (name or "").strip()
    if not cleaned:
        raise BizError(message="合同类型不能为空")
    existing = db.execute(
        select(TemplateCategory).where(TemplateCategory.name == cleaned)
    ).scalars().first()
    if existing is not None:
        return existing
    item = TemplateCategory(name=cleaned)
    db.add(item)
    db.flush()
    return item


def create_category(db: Session, name: str, sort_order: int = 0) -> TemplateCategory:
    existing = db.execute(
        select(TemplateCategory).where(TemplateCategory.name == (name or "").strip())
    ).scalars().first()
    if existing is not None:
        raise BizError(message=f"合同类型「{name}」已存在")
    item = ensure_category(db, name)
    item.sort_order = sort_order
    db.commit()
    db.refresh(item)
    return item


def delete_category(db: Session, category_id: int) -> None:
    item = db.get(TemplateCategory, category_id)
    if item is None:
        raise NotFoundError("合同类型不存在")
    in_use = db.execute(
        select(func.count())
        .select_from(ContractTemplate)
        .where(ContractTemplate.category == item.name, ContractTemplate.deleted_at.is_(None))
    ).scalar_one()
    if in_use:
        raise BizError(message=f"该类型下还有 {in_use} 个模板，无法删除")
    db.delete(item)
    db.commit()


def seed_categories_from_templates(db: Session) -> int:
    """把存量模板里手打的分类灌进词表（一次性迁移，可重复执行）。"""
    rows = db.execute(
        select(ContractTemplate.category)
        .where(ContractTemplate.category.is_not(None), ContractTemplate.deleted_at.is_(None))
        .distinct()
    ).all()
    created = 0
    for (name,) in rows:
        if not (name or "").strip():
            continue
        exists = db.execute(
            select(TemplateCategory).where(TemplateCategory.name == name.strip())
        ).scalars().first()
        if exists is None:
            db.add(TemplateCategory(name=name.strip()))
            created += 1
    if created:
        db.commit()
    return created


# ===== 合同生成（需求⑦）=====

# 草稿预览里未填的变量不能渲染成空串：那样占位符会在预览中凭空消失，
# 既看不出该在哪里填，也看不出对应哪个变量。用方括号包住变量名做可见标记。
PREVIEW_EMPTY_MARKER = "【{key}】"
# 预览渲染逻辑的版本号，参与缓存键。只按取值做键的话，改了渲染方式
# （比如这里的占位标记）后，同一组取值仍会命中旧文件，改动看起来"没生效"。
PREVIEW_RENDER_VERSION = 2


def _preview_value(variables: dict, field: dict) -> str:
    """预览取值：有填写用填写值，其次用字段默认值，都没有则给可见占位标记。"""
    value = str(variables.get(field["key"]) or field.get("default") or "").strip()
    return value or PREVIEW_EMPTY_MARKER.format(key=field["key"])


def render_contract(
    db: Session, item: ContractTemplate, variables: dict
) -> tuple[str, str, list[str]]:
    """在**标准化模板**上做 docxtpl 确定性填充，返回 (路径, 文件名, 缺失变量)。

    缺失的占位变量补空串，避免 docxtpl 抛错中断生成；缺失清单回给前端提示。
    路由层负责在真正生成前拦住必填项，这里的兜底是给"非必填留空"用的。
    """
    required = parse_variables(item)
    context = {key: (variables.get(key) or "") for key in required}
    context.update({key: value for key, value in (variables or {}).items() if key not in context})

    output_dir = word_generator.ensure_output_dir(settings.OUTPUT_DIR)
    # 文件名带 uuid 片段：秒级时间戳在同模板同秒并发生成时会互相覆盖
    file_name = f"{word_generator.safe_filename(item.name, suffix='')}_{uuid.uuid4().hex[:8]}.docx"
    output_path = str(output_dir / file_name)

    try:
        word_generator.render_template(working_path(item), context, output_path)
    except Exception as exc:  # noqa: BLE001 - 模板语法/变量错误要回给前端
        raise BizError(message=f"合同生成失败：{exc}") from exc

    missing = [key for key in required if not str(variables.get(key) or "").strip()]
    return output_path, file_name, missing


def missing_required(item: ContractTemplate, variables: dict) -> list[str]:
    """必填字段中未填写的键（生成前拦截，不再"补空串还提示成功"）。"""
    return [
        field["key"]
        for field in parse_fields(item)
        if field.get("required") and not str(variables.get(field["key"]) or "").strip()
    ]


def render_preview(item: ContractTemplate, variables: dict) -> tuple[Path, str]:
    """按当前取值渲染一份草稿用于预览（不落生成记录）。

    文件名取「模板版本 + 取值」的内容哈希，因此同一组取值反复预览只会转一次，
    也不会在生产目录里堆垃圾文件。
    """
    import hashlib

    working = working_path(item)
    payload = json.dumps(
        {
            "renderer": PREVIEW_RENDER_VERSION,
            "template": item.id,
            "version": item.version,
            "path": working,
            "values": variables,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32]
    target = Path(settings.CONTRACT_PREVIEW_DIR) / f"{digest}.docx"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        return target, digest

    context = {field["key"]: _preview_value(variables, field) for field in parse_fields(item)}
    if not context:
        context = {
            key: _preview_value(variables, {"key": key}) for key in parse_variables(item)
        }
    try:
        word_generator.render_template(working, context, str(target))
    except Exception as exc:  # noqa: BLE001 - 模板错误要回给前端
        raise BizError(message=f"预览渲染失败：{exc}") from exc
    return target, digest
