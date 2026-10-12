"""校验分类检索合同工作流的单块输出，并转为审查页面的风险结构。"""

import json
import re
import unicodedata


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def _source_text_matches(source_text: str, chunk_text: str) -> bool:
    """允许模型用省略号摘取同一块内的连续片段或附加相邻条款号。"""
    text = _compact(chunk_text)
    quote = _compact(source_text)
    if quote in text:
        return True
    parts = [part for part in re.split(r"(?:\.{2,}|…+)", quote) if part]
    if not parts:
        return False
    cursor = 0
    for part in parts:
        position = text.find(part, cursor)
        if position < 0:
            without_number = re.sub(r"^\d+(?:\.\d+)*(?:\(\d+\))?", "", part)
            if len(without_number) < 8:
                return False
            position = text.find(without_number, cursor)
            part = without_number
        is_clause_number = bool(re.fullmatch(r"第[一二三四五六七八九十百千万零0-9]+条", part))
        if position < 0 or (len(part) < 8 and not is_clause_number):
            return False
        cursor = position + len(part)
    return True


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 缺失")
    return value.strip()


def validate_contract_report(outputs: dict, chunk_text: str) -> list[dict]:
    """失败时抛错，由审查任务将该块标记为需人工复核。"""
    report = outputs.get("report")
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except json.JSONDecodeError as exc:
            raise ValueError("合同审查报告不是合法 JSON") from exc
    if not isinstance(report, dict) or not isinstance(report.get("risks"), list):
        raise ValueError("合同审查报告缺少 risks 数组")

    sources = []
    for key in ("legal_sources", "policy_sources"):
        value = outputs.get(key)
        if not isinstance(value, list):
            raise ValueError(f"合同审查结果缺少 {key} 检索证据")
        sources.extend(item for item in value if isinstance(item, dict))
    case_sources = outputs.get("case_sources")
    if not isinstance(case_sources, list):
        raise ValueError("合同审查结果缺少 case_sources 检索证据")

    result = []
    for index, item in enumerate(report["risks"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 项风险格式错误")
        clause = _required_text(item.get("sourceText"), "sourceText")
        validation_notes = []
        if not _source_text_matches(clause, chunk_text):
            validation_notes.append("风险原文未在当前文本块中核对")
        level = _required_text(item.get("level"), "level")
        if level not in ("高", "中", "低"):
            raise ValueError(f"第 {index} 项风险等级无效")
        analysis = _required_text(item.get("analysis"), "analysis")
        suggestion = _required_text(item.get("suggestion"), "suggestion")
        case_analysis = _required_text(item.get("caseAnalysis"), "caseAnalysis")
        if case_analysis != "未检索到" and not case_sources:
            validation_notes.append("案例分析缺少本次检索依据")
        citations = item.get("citations")
        if not isinstance(citations, list):
            raise ValueError(f"第 {index} 项缺少 citations 数组")
        if not citations:
            validation_notes.append("未提供法规或制度引用")

        checked = []
        for citation in citations:
            if not isinstance(citation, dict):
                validation_notes.append("引用格式错误，未作为已核实依据展示")
                continue
            name = str(citation.get("documentName") or "").strip()
            section = str(citation.get("section") or "").strip()
            if not name or not section:
                validation_notes.append("引用缺少资料名称或章节，未作为已核实依据展示")
                continue
            url_value = citation.get("url")
            if url_value is None:
                url = ""
            elif isinstance(url_value, str):
                url = url_value.strip()
            else:
                validation_notes.append(f"《{name}》{section}的链接格式错误，未作为已核实依据展示")
                continue
            if url and not url.startswith(("https://", "http://")):
                validation_notes.append(f"《{name}》{section}的链接无效，未作为已核实依据展示")
                continue
            if not any(
                all(part in json.dumps(source, ensure_ascii=False) for part in (name, section))
                and (not url or url in json.dumps(source, ensure_ascii=False))
                for source in sources
            ):
                validation_notes.append(f"《{name}》{section}未在本次法规或制度检索结果中核对")
                continue
            checked.append({"document_name": name, "section": section, "url": url})

        result.append({
            "clause": clause,
            "risk_level": {"高": "high", "中": "medium", "低": "low"}[level],
            "analysis": analysis,
            "citations": checked,
            "case_analysis": case_analysis if case_analysis != "未检索到" else "",
            "needs_review": bool(validation_notes),
            "validation_notes": validation_notes,
            "violations": [],
            "reference_case": None,
            "suggestion": suggestion,
        })
    return result
