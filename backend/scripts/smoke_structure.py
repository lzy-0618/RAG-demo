"""模板结构化冒烟测试（P1）：扫描 → 回写 → 自检 → 端到端转 PDF。

用法（在 backend/ 下执行）：
    .venv/bin/python scripts/smoke_structure.py
脚本会现场合成一份含四类"待填"痕迹的 .docx，不需要外部素材。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Pt  # noqa: E402

from app.core.exceptions import BizError  # noqa: E402
from app.services import docx_convert, template_rewrite, template_scan, word_generator  # noqa: E402

WORK = Path("var/structure-smoke")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ✅ {label}")
    else:
        failures.append(label)
        print(f"  ❌ {label} {detail}")


def build_fixture(path: Path) -> None:
    """合成模板：覆盖下划线填空 / 标签后为空 / 已有占位符 / 表格空单元格。"""
    doc = Document()
    title = doc.add_paragraph()
    run = title.add_run("钢材采购合同模板")
    run.font.size = Pt(18)
    run.font.bold = True

    for label in ("甲方（采购方）：", "乙方（供应方）："):
        para = doc.add_paragraph()
        para.add_run(label)
        blank = para.add_run("            ")
        blank.font.underline = True  # 下划线填空：回写后占位符必须继承下划线

    doc.add_paragraph("合同金额：")

    para = doc.add_paragraph()
    para.add_run("签订日期：")
    para.add_run("{{ sign_date }}")

    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "金额"
    table.cell(1, 0).text = "钢材"
    doc.add_paragraph("备注：以上条款经双方确认后生效。")

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def pick(candidates: list[dict], kind: str, index: int = 0) -> dict:
    matched = [item for item in candidates if item["kind"] == kind]
    if len(matched) <= index:
        raise SystemExit(f"未找到第 {index + 1} 个 {kind} 候选，实际候选见上方输出")
    return matched[index]


def main() -> int:
    fixture = WORK / "fixture.docx"
    standardized = WORK / "standardized.docx"
    build_fixture(fixture)

    print("1) 扫描候选")
    scan = template_scan.scan_document(fixture)
    print("--- 文档大纲 ---")
    print(scan.outline)
    print("--- 候选 ---")
    for item in scan.candidates:
        print(f"  [{item['id']}] {item['kind']:<12} {item['anchor']:<5} {item['context'][:40]!r}")

    kinds = {item["kind"] for item in scan.candidates}
    for kind in ("blank", "label_empty", "jinja", "empty_cell"):
        check(f"识别出 {kind} 候选", kind in kinds, f"实际 kinds={sorted(kinds)}")

    print("\n2) 回写标准化模板")
    fields = [
        {"key": "party_a_name", "label": "甲方名称", "type": "text", "required": True,
         "candidate_id": pick(scan.candidates, "blank", 0)["id"]},
        {"key": "party_b_name", "label": "乙方名称", "type": "text", "required": True,
         "candidate_id": pick(scan.candidates, "blank", 1)["id"]},
        {"key": "contract_amount", "label": "合同金额", "type": "number", "required": True,
         "candidate_id": pick(scan.candidates, "label_empty")["id"]},
        # 已有占位符：走"改名"路径，键由 AI 重新给出语义名
        {"key": "sign_date", "label": "签订日期", "type": "date", "required": True,
         "candidate_id": pick(scan.candidates, "jinja")["id"]},
        {"key": "unit_price", "label": "单价", "type": "number", "required": False,
         "candidate_id": pick(scan.candidates, "empty_cell")["id"]},
    ]
    result = template_rewrite.rewrite_document(fixture, fields, standardized)
    print(f"  写入字段：{result['applied_keys']}")
    print(f"  写入方式：{result['write_modes']}")
    if result["warnings"]:
        print(f"  警告：{result['warnings']}")

    expected = {field["key"] for field in fields}
    check("自检：字段全部生成占位符", set(result["applied_keys"]) == expected)
    check("自检：无遗漏变量", not result["missing_in_document"], str(result["missing_in_document"]))

    print("\n3) 校验产物")
    found = set(word_generator.extract_template_variables(standardized))
    check("docxtpl 解析出的变量与字段一致", found == expected, f"found={sorted(found)}")

    doc = Document(str(standardized))
    paragraphs = [p.text for p in doc.paragraphs]
    check("下划线填空已变为占位符", any("{{ party_a_name }}" in t for t in paragraphs),
          str(paragraphs[:4]))
    check("标签后插入占位符", any("合同金额：{{ contract_amount }}" in t for t in paragraphs))
    check("已有占位符被改名", any("{{ sign_date }}" in t for t in paragraphs))
    cell_text = doc.tables[0].cell(1, 1).text
    check("表格空单元格已填充", "{{ unit_price }}" in cell_text, repr(cell_text))

    # 格式保留：占位符所在 run 必须仍带下划线（原填空是下划线）
    underline_kept = False
    for para in doc.paragraphs:
        for run in para.runs:
            if "{{ party_a_name }}" in run.text and run.font.underline:
                underline_kept = True
    check("占位符继承了下划线格式", underline_kept)

    print("\n4) 用 docxtpl 渲染填值")
    rendered = WORK / "rendered.docx"
    word_generator.render_template(
        str(standardized),
        {"party_a_name": "某钢股份有限公司", "party_b_name": "某某钢铁贸易有限公司",
         "contract_amount": "2350000", "sign_date": "2026-09-14", "unit_price": "4700"},
        str(rendered),
    )
    text = "\n".join(p.text for p in Document(str(rendered)).paragraphs)
    check("渲染结果包含填入的甲方", "某钢股份有限公司" in text)
    check("渲染结果不再是占位符", "{{" not in text)

    print("\n5) 端到端：标准化模板转 PDF 并做中文自检")
    try:
        pdf = asyncio.run(docx_convert.convert_to_pdf(rendered))
        spans, ratio = docx_convert._cjk_ink_ratio(pdf)
        check("生成 PDF", pdf.exists() and pdf.stat().st_size > 0)
        check("中文墨迹正常", ratio >= 0.005, f"ratio={ratio:.2%} spans={spans}")
    except BizError as exc:
        check("生成 PDF", False, exc.message)

    print("\n6) 回归：只给 anchor、不给 candidate_id（应用六的实际输出形态）")
    anchor_only = WORK / "anchor_only.docx"
    result = template_rewrite.rewrite_document(
        fixture,
        [
            {"key": "party_a_name", "label": "甲方名称", "required": True,
             "candidate_id": "", "anchor": pick(scan.candidates, "blank", 0)["anchor"]},
            {"key": "contract_amount", "label": "合同金额", "required": True,
             "candidate_id": "", "anchor": pick(scan.candidates, "label_empty")["anchor"]},
            {"key": "unit_price", "label": "单价", "candidate_id": "",
             "anchor": pick(scan.candidates, "empty_cell")["anchor"]},
        ],
        anchor_only,
    )
    check("按锚点回退可定位到填空处", result["write_modes"]["party_a_name"] == "replace",
          result["write_modes"])
    texts = [p.text for p in Document(str(anchor_only)).paragraphs]
    check("下划线痕迹已清除（占位符未追加在下划线之后）",
          any(t.strip() == "甲方（采购方）：{{ party_a_name }}" for t in texts), str(texts[:4]))
    check("标签后插入位置正确",
          any("合同金额：{{ contract_amount }}" in t for t in texts))

    print("\n7) 异常路径")
    try:
        template_rewrite.rewrite_document(fixture, [], WORK / "x.docx")
        check("空字段清单应报错", False, "未抛异常")
    except BizError as exc:
        check("空字段清单应报错", "为空" in exc.message, exc.message)

    bad = [dict(fields[0], candidate_id="c999")]
    try:
        template_rewrite.rewrite_document(fixture, bad, WORK / "x.docx")
        check("不存在的候选应报错", False, "未抛异常")
    except BizError as exc:
        check("不存在的候选应报错", "锚点" in exc.message, exc.message)

    print()
    if failures:
        print(f"❌ 失败 {len(failures)} 项：{failures}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
