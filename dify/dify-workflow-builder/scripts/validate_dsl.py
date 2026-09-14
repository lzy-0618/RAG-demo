#!/usr/bin/env python3
"""Validate a Dify 1.17 DSL file.

Two layers, because each catches a different class of bug:

**Layer 1 — envelope/grammar lint (always runs, needs only PyYAML).**
Catches the mistakes that make Dify either refuse the import or render a broken
canvas: top-level ``kind``/``version``/``dependencies``, node ``type: custom`` vs
``data.type``, missing edge handles, node types and output keys that do not exist,
dangling ``value_selector`` / ``{{#node.key#}}`` references, ``variable`` instead
of ``name`` in environment variables, hardcoded credentials, unreachable nodes.

**Layer 2 — real pydantic validation (runs when ``graphon`` is importable).**
That means inside the Dify API container, where each node's ``data`` is fed to the
very model the runtime uses. Layer 1 encodes what those models require, so the two
agree — but Layer 2 is authoritative.

Usage::

    python scripts/validate_dsl.py app.yml
    python scripts/validate_dsl.py app.yml --strict      # warnings become failures
    python scripts/validate_dsl.py app.yml --json        # machine-readable report
    python scripts/validate_dsl.py app.yml --shallow     # skip pydantic layer
    bash scripts/validate.sh                             # same checks inside Dify

Exit codes: 0 clean, 1 errors, 2 usage/dependency problem.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dify_dsl import (  # noqa: E402
        BUILTIN_NODE_TYPES,
        CONTAINER_INNER_RENDERERS,
        CONTAINER_INNER_TYPES,
        CURRENT_DSL_VERSION,
        ENV_VAR_TYPES,
        START_VAR_TYPES,
        SYS_VARS,
    )
except ImportError:  # pragma: no cover - validator must survive standalone use
    CONTAINER_INNER_RENDERERS = {
        "iteration-start": "custom-iteration-start",
        "loop-start": "custom-loop-start",
        "loop-end": "custom-loop-end",
    }
    BUILTIN_NODE_TYPES = frozenset(
        {
            "start", "end", "answer", "llm", "knowledge-retrieval", "if-else", "code",
            "template-transform", "question-classifier", "http-request", "tool",
            "datasource", "variable-aggregator", "variable-assigner", "loop", "loop-start",
            "loop-end", "iteration", "iteration-start", "parameter-extractor", "assigner",
            "document-extractor", "list-operator", "agent", "human-input",
            "trigger-webhook", "trigger-schedule", "trigger-plugin",
        }
    )
    CONTAINER_INNER_TYPES = frozenset({"iteration-start", "loop-start", "loop-end"})
    CURRENT_DSL_VERSION = "0.7.0"
    ENV_VAR_TYPES = frozenset(
        {"string", "secret", "number", "integer", "float", "boolean", "object",
         "array[string]", "array[number]", "array[object]", "array[boolean]", "array[file]", "array[any]"}
    )
    START_VAR_TYPES = frozenset(
        {"text-input", "select", "paragraph", "number", "file", "file-list", "checkbox",
         "json_object", "external_data_tool"}
    )
    SYS_VARS = frozenset(
        {"query", "files", "conversation_id", "user_id", "dialogue_count", "app_id", "workflow_id",
         "workflow_run_id", "timestamp", "document_id", "original_document_id", "batch", "dataset_id",
         "datasource_type", "datasource_info", "invoke_from"}
    )

APP_MODES = frozenset({"workflow", "advanced-chat", "completion", "chat", "agent-chat"})

#: Output keys each node kind exposes (verified against graphon 1.17 node sources).
#: ``None`` means the key set is dynamic — the checker then only verifies the node
#: exists, because tool/agent parameter schemas are plugin-defined.
NODE_OUTPUTS: Mapping[str, frozenset[str] | None] = {
    "llm": frozenset({"text", "reasoning_content", "usage", "finish_reason", "structured_output", "files"}),
    "knowledge-retrieval": frozenset({"result"}),
    "http-request": frozenset({"body", "status_code", "headers", "files"}),
    "template-transform": frozenset({"output"}),
    "document-extractor": frozenset({"text"}),
    "list-operator": frozenset({"result"}),
    "variable-aggregator": frozenset({"output"}),
    "variable-assigner": frozenset({"output"}),
    "assigner": frozenset({"output"}),
    "question-classifier": frozenset({"class_name", "class_id", "usage"}),
    "iteration": frozenset({"output", "item", "index"}),
    "loop": None,
    "tool": None,
    "agent": None,
    "human-input": None,
    "datasource": None,
    "start": frozenset(),      # replaced by the node's declared variables
    "code": frozenset(),       # replaced by the node's declared outputs
    "parameter-extractor": frozenset({"__is_success", "__reason"}),
    "end": frozenset(),
    "answer": frozenset(),
    "if-else": frozenset(),
    "iteration-start": frozenset(),
    "loop-start": frozenset(),
    "loop-end": frozenset(),
}

#: Which data keys Dify 1.17 requires, per node kind. Sourced from
#: graphon.nodes.*.entities and core.workflow.nodes.*.entities model fields.
REQUIRED_DATA_KEYS: Mapping[str, tuple[str, ...]] = {
    "start": ("variables",),
    "end": ("outputs",),
    "answer": ("answer",),
    "llm": ("model", "prompt_template", "context"),
    "code": ("variables", "code_language", "code", "outputs"),
    "knowledge-retrieval": ("dataset_ids", "retrieval_mode"),
    "if-else": (),
    "question-classifier": ("query_variable_selector", "model", "classes"),
    "parameter-extractor": ("model", "query", "parameters", "reasoning_mode"),
    "template-transform": ("variables", "template"),
    "document-extractor": ("variable_selector",),
    "variable-aggregator": ("output_type", "variables"),
    "assigner": ("items",),
    "iteration": ("start_node_id", "iterator_selector", "output_selector"),
    "loop": ("start_node_id", "loop_count", "break_conditions", "logical_operator"),
    "http-request": ("method", "url", "authorization", "headers", "params"),
    "list-operator": ("filter_by", "order_by", "limit"),
    "tool": ("provider_id", "provider_type", "provider_name", "tool_name", "tool_label",
             "tool_configurations", "tool_parameters"),
    "agent": ("agent_strategy_provider_name", "agent_strategy_name", "agent_parameters"),
}

#: Comparison operators the 1.17 condition model accepts.
COMPARISON_OPERATORS = frozenset(
    {
        "is", "is not", "contains", "not contains", "start with", "end with",
        "empty", "not empty", "=", "≠", ">", "<", "≥", "≤", "is null", "is not null",
        "in", "not in", "all of", "exists", "not exists",
    }
)

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\."),
)

VAR_REF_RE = re.compile(r"\{\{#([A-Za-z0-9_\-]+)\.([A-Za-z0-9_\-]+)#\}\}")


class Report:
    """Collects errors and warnings for one file."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)


# --------------------------------------------------------------------------
# Layer 2 — real pydantic models, available only inside the Dify container
# --------------------------------------------------------------------------


def load_pydantic_models() -> dict[str, Any] | None:
    """Map node kind -> the pydantic model Dify's runtime validates ``data`` with."""
    import importlib

    specs = {
        "start": ("graphon.nodes.start.entities", "StartNodeData"),
        "end": ("graphon.nodes.end.entities", "EndNodeData"),
        "answer": ("graphon.nodes.answer.entities", "AnswerNodeData"),
        "llm": ("graphon.nodes.llm.entities", "LLMNodeData"),
        "code": ("graphon.nodes.code.entities", "CodeNodeData"),
        "if-else": ("graphon.nodes.if_else.entities", "IfElseNodeData"),
        "knowledge-retrieval": ("core.workflow.nodes.knowledge_retrieval.entities", "KnowledgeRetrievalNodeData"),
        "variable-aggregator": ("graphon.nodes.variable_aggregator.entities", "VariableAggregatorNodeData"),
        "variable-assigner": ("graphon.nodes.variable_aggregator.entities", "VariableAggregatorNodeData"),
        "assigner": ("graphon.nodes.variable_assigner.v2.entities", "VariableAssignerNodeData"),
        "template-transform": ("graphon.nodes.template_transform.entities", "TemplateTransformNodeData"),
        "iteration": ("graphon.nodes.iteration.entities", "IterationNodeData"),
        "loop": ("graphon.nodes.loop.entities", "LoopNodeData"),
        "http-request": ("graphon.nodes.http_request.entities", "HttpRequestNodeData"),
        "tool": ("graphon.nodes.tool.entities", "ToolNodeData"),
        "parameter-extractor": ("graphon.nodes.parameter_extractor.entities", "ParameterExtractorNodeData"),
        "question-classifier": ("graphon.nodes.question_classifier.entities", "QuestionClassifierNodeData"),
        "document-extractor": ("graphon.nodes.document_extractor.entities", "DocumentExtractorNodeData"),
        "list-operator": ("graphon.nodes.list_operator.entities", "ListOperatorNodeData"),
        "agent": ("core.workflow.nodes.agent.entities", "AgentNodeData"),
        "iteration-start": ("graphon.nodes.iteration.entities", "IterationStartNodeData"),
        "loop-start": ("graphon.nodes.loop.entities", "LoopStartNodeData"),
        "loop-end": ("graphon.nodes.loop.entities", "LoopEndNodeData"),
    }
    models: dict[str, Any] = {}
    for kind, (module_name, class_name) in specs.items():
        try:
            module = importlib.import_module(module_name)
            models[kind] = getattr(module, class_name)
        except Exception:  # noqa: BLE001 - absent module simply means no deep check
            continue
    return models or None


# --------------------------------------------------------------------------
# Layer 1 — envelope and grammar
# --------------------------------------------------------------------------


def _iter_selectors(value: Any, path: str = "") -> Iterable[tuple[str, list[str]]]:
    """Yield every 2-element [node_id, key] selector found in a node's data.

    Dify stores every variable reference in node data as a selector pair, except a
    handful of singular fields (``query`` on parameter-extractor, ``variable`` on
    list-operator, ``iterator_selector``/``output_selector`` on iteration) which are
    also pairs but live under a non-``value_selector`` key.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if key in PAIR_VALUE_KEYS and _is_pair(item):
                yield child, list(item)
                continue
            yield from _iter_selectors(item, child)
        return
    if isinstance(value, list):
        if path.endswith("value_selector") and _is_pair(value):
            yield path, list(value)
            return
        for index, item in enumerate(value):
            yield from _iter_selectors(item, f"{path}[{index}]")


#: Fields whose value is a bare [node, key] pair rather than a wrapped selector.
PAIR_VALUE_KEYS = frozenset(
    {
        "value_selector",
        "query",
        "variable",
        "iterator_selector",
        "output_selector",
    }
)


def _is_pair(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(isinstance(x, str) for x in value)


def _extra_selectors(data: Mapping[str, Any]) -> Iterable[tuple[str, list[str]]]:
    """Selectors living in places the generic walk cannot recognise.

    Two cases: an HTTP request body row of ``type: variable`` keeps its selector in
    ``value``, which plain-text rows also use for literal content; and a loop's
    ``loop_variables`` carry a selector in ``value`` only when ``value_type`` is
    ``variable``. Both have to be read here rather than through ``PAIR_VALUE_KEYS``.
    """
    body = data.get("body")
    if isinstance(body, Mapping):
        for index, row in enumerate(body.get("data") or []):
            if isinstance(row, Mapping) and row.get("type") == "variable" and _is_pair(row.get("value")):
                yield f"body.data[{index}].value", list(row["value"])

    for index, variable in enumerate(data.get("loop_variables") or []):
        if (
            isinstance(variable, Mapping)
            and variable.get("value_type") == "variable"
            and _is_pair(variable.get("value"))
        ):
            yield f"loop_variables[{index}].value", list(variable["value"])


def declared_outputs(node: Mapping[str, Any]) -> frozenset[str] | None:
    """Output keys a node exposes, or ``None`` when it is plugin-defined."""
    data = node.get("data", {})
    kind = data.get("type", "")
    if kind == "start":
        return frozenset(v.get("variable", "") for v in data.get("variables", []) if v.get("variable"))
    if kind == "code":
        return frozenset((data.get("outputs") or {}).keys())
    if kind == "parameter-extractor":
        base = set(NODE_OUTPUTS.get(kind) or ())
        base.update(p.get("name", "") for p in data.get("parameters", []) if p.get("name"))
        return frozenset(base)
    return NODE_OUTPUTS.get(kind, None)


def check_top_level(dsl: Mapping[str, Any], report: Report) -> None:
    for key in ("app", "kind", "version", "workflow"):
        if key not in dsl:
            report.error(f"顶层缺少必填字段 `{key}`")

    kind = dsl.get("kind")
    if kind is not None and kind != "app":
        report.error(f"`kind` 必须是 `app`，实际是 `{kind}`（Dify 导入时会强制改写，写别的值是误导）")

    if "dependencies" not in dsl:
        report.warn("顶层缺少 `dependencies`（真实导出会带上，缺省时导入可接受）")

    app = dsl.get("app") or {}
    if not isinstance(app, Mapping):
        report.error("`app` 必须是对象")
        return
    mode = app.get("mode")
    if mode not in APP_MODES:
        report.error(f"`app.mode` 取值非法：{mode!r}，允许 {sorted(APP_MODES)}")
    if not app.get("name"):
        report.warn("`app.name` 为空，导入后应用名会是占位值")

    version = dsl.get("version")
    if isinstance(version, str):
        try:
            major, minor = (int(part) for part in version.split(".")[:2])
            cur_major, cur_minor = (int(part) for part in CURRENT_DSL_VERSION.split(".")[:2])
            if major == cur_major and minor < cur_minor:
                report.warn(
                    f"version={version} 低于 Dify 1.17 的 {CURRENT_DSL_VERSION}，会以「有警告」状态导入；"
                    "Dify 不做任何迁移，图结构必须本身就是 1.17 格式。建议直接写 "
                    f"{CURRENT_DSL_VERSION}"
                )
        except ValueError:
            report.warn(f"version={version!r} 不是合法的 x.y.z")
    elif version is not None:
        report.error(f"`version` 必须是字符串，实际是 {type(version).__name__}")


def check_variables(dsl: Mapping[str, Any], report: Report) -> None:
    workflow = dsl.get("workflow") or {}
    for field in ("environment_variables", "conversation_variables"):
        entries = workflow.get(field) or []
        if not isinstance(entries, list):
            report.error(f"`workflow.{field}` 必须是数组")
            continue
        for index, entry in enumerate(entries):
            where = f"workflow.{field}[{index}]"
            if not isinstance(entry, Mapping):
                report.error(f"{where} 必须是对象")
                continue
            if "name" not in entry:
                hint = "；`variable` 不是有效键，导入会报 missing name" if "variable" in entry else ""
                report.error(f"{where} 缺少 `name`{hint}")
            if "value_type" not in entry:
                report.error(f"{where} 缺少 `value_type`")
            elif entry["value_type"] not in ENV_VAR_TYPES:
                report.error(f"{where}.value_type={entry['value_type']!r} 非法，允许 {sorted(ENV_VAR_TYPES)}")
            if "value" not in entry:
                report.error(f"{where} 缺少 `value`（空字符串也要写出来）")


def check_node_envelope(node: Mapping[str, Any], report: Report, seen_ids: dict[str, str]) -> None:
    node_id = node.get("id")
    if not node_id:
        report.error("存在缺少 `id` 的节点")
        return
    if node_id in seen_ids:
        report.error(f"节点 id 重复：`{node_id}`")
    seen_ids[node_id] = str((node.get("data") or {}).get("type", ""))

    top_type = node.get("type")
    data = node.get("data")
    kind = (data or {}).get("type") if isinstance(data, Mapping) else None
    if kind in CONTAINER_INNER_TYPES:
        expected_renderer = CONTAINER_INNER_RENDERERS.get(str(kind))
        if top_type != expected_renderer:
            report.warn(
                f"容器子节点 `{node_id}` 的顶层 type={top_type!r}，应为 {expected_renderer!r}；"
                "容器内部记账节点用 custom-*-start / custom-*-end 渲染"
            )
    elif top_type != "custom":
        report.error(
            f"节点 `{node_id}` 顶层 type={top_type!r}，必须为 `custom`；"
            "语义节点类型放在 data.type（写成 type: llm 会导致前端找不到渲染组件）"
        )

    data = node.get("data")
    if not isinstance(data, Mapping):
        report.error(f"节点 `{node_id}` 缺少 `data`")
        return

    kind = data.get("type")
    if not kind:
        report.error(f"节点 `{node_id}` 的 data 缺少 `type`")
    elif kind not in BUILTIN_NODE_TYPES:
        report.error(f"节点 `{node_id}`: 未知 data.type `{kind}`")

    for key in ("title", "desc", "selected"):
        if key not in data:
            report.warn(f"节点 `{node_id}` 的 data 缺少 `{key}`（真实导出会带上，前端依赖它渲染）")
    if kind in CONTAINER_INNER_TYPES:
        # Container bookkeeping nodes are ReactFlow children: relative position +
        # parentId, and no node-level `selected`/`positionAbsolute`.
        if "position" not in node:
            report.warn(f"容器子节点 `{node_id}` 缺少 position")
    else:
        if "selected" not in node:
            report.warn(f"节点 `{node_id}` 缺少节点级 `selected`")
        if "position" not in node or "positionAbsolute" not in node:
            report.warn(f"节点 `{node_id}` 缺少 position/positionAbsolute，画布上会堆在原点")

    if kind in CONTAINER_INNER_TYPES:
        return

    required = REQUIRED_DATA_KEYS.get(kind, ())
    missing = [key for key in required if key not in data]
    if missing:
        report.error(f"节点 `{node_id}` ({kind}) 缺少必填字段：{', '.join(missing)}")

    if kind == "code" and "code_language" not in data and "language" in data:
        report.error(
            f"节点 `{node_id}` 用了 `language`，Code 节点的字段名是 `code_language`（`language` 会被静默忽略）"
        )


def check_node_details(node: Mapping[str, Any], report: Report) -> None:
    data = node.get("data", {})
    kind = data.get("type", "")
    node_id = node.get("id", "?")

    if kind == "start":
        for index, variable in enumerate(data.get("variables") or []):
            where = f"节点 `{node_id}` 输入变量[{index}]"
            if not variable.get("variable"):
                report.error(f"{where} 缺少 `variable`")
            if not variable.get("label"):
                report.error(f"{where} 缺少 `label`")
            vtype = variable.get("type")
            if vtype not in START_VAR_TYPES:
                report.error(f"{where}.type={vtype!r} 非法，允许 {sorted(START_VAR_TYPES)}")

    elif kind == "end":
        outputs = data.get("outputs")
        if not isinstance(outputs, list):
            report.error(f"节点 `{node_id}` (end) 的 outputs 必须是数组")
        else:
            for index, output in enumerate(outputs):
                where = f"节点 `{node_id}` 输出[{index}]"
                if "value_type" not in output:
                    report.error(
                        f"{where} 缺少 `value_type`（End 的 outputs 需要 value_type，"
                        "只写 value/value_selector 是 0.x 写法）"
                    )
                if "value_selector" not in output:
                    report.error(f"{where} 缺少 `value_selector`")
                if not output.get("variable"):
                    report.error(f"{where} 缺少 `variable`")

    elif kind == "answer":
        if not isinstance(data.get("answer"), str) or not data.get("answer"):
            report.error(f"节点 `{node_id}` (answer) 的 `answer` 不能为空")

    elif kind == "llm":
        model = data.get("model") or {}
        for key in ("provider", "name", "mode"):
            if not model.get(key):
                report.error(f"节点 `{node_id}` 的 model 缺少 `{key}`")
        if model.get("mode") not in (None, "chat", "completion"):
            report.error(f"节点 `{node_id}` 的 model.mode={model.get('mode')!r} 非法")
        for key in ("vision", "memory", "structured_output", "retry_config"):
            if key not in data:
                report.warn(f"节点 `{node_id}` 的 data 缺少 `{key}`（1.17 真实导出会带上）")

    elif kind == "knowledge-retrieval":
        if not isinstance(data.get("dataset_ids"), list):
            report.error(f"节点 `{node_id}` 的 dataset_ids 必须是数组（暂不绑定就写 []）")
        if data.get("retrieval_mode") not in ("single", "multiple"):
            report.error(f"节点 `{node_id}` 的 retrieval_mode 必须是 single 或 multiple")
        if data.get("query_variable_selector") is None:
            report.error(f"节点 `{node_id}` 缺少 query_variable_selector")

    elif kind == "if-else":
        cases = data.get("cases")
        if not isinstance(cases, list) or not cases:
            report.error(f"节点 `{node_id}` (if-else) 需要非空的 cases 数组")
        else:
            for index, case in enumerate(cases):
                where = f"节点 `{node_id}` case[{index}]"
                if not case.get("case_id"):
                    report.error(f"{where} 缺少 case_id")
                if case.get("id") != case.get("case_id"):
                    report.error(
                        f"{where} 的 `id` 必须等于 `case_id`（运行时按 id 匹配分支），"
                        f"实际 id={case.get('id')!r} case_id={case.get('case_id')!r}"
                    )
                for cond_index, cond in enumerate(case.get("conditions") or []):
                    check_condition(cond, f"{where}.conditions[{cond_index}]", report)
            if data.get("logical_operator") not in ("and", "or", None):
                report.error(f"节点 `{node_id}` 的 logical_operator 只能是 and 或 or")

    elif kind == "loop":
        for index, cond in enumerate(data.get("break_conditions") or []):
            check_condition(cond, f"节点 `{node_id}` break_conditions[{index}]", report)

    elif kind == "code":
        outputs = data.get("outputs")
        if not isinstance(outputs, Mapping):
            report.error(f"节点 `{node_id}` 的 outputs 必须是对象（形如 变量名: {children, type}）")
        else:
            for name, spec in outputs.items():
                if not isinstance(spec, Mapping) or "type" not in spec:
                    report.error(f"节点 `{node_id}` 的 outputs.{name} 缺少 `type`")
                elif "children" not in spec:
                    report.warn(f"节点 `{node_id}` 的 outputs.{name} 缺少 `children`（真实导出为 children: null）")
        if not data.get("code"):
            report.error(f"节点 `{node_id}` 的 code 不能为空")

    elif kind == "variable-aggregator":
        variables = data.get("variables")
        if not isinstance(variables, list) or not variables:
            report.error(f"节点 `{node_id}` (variable-aggregator) 的 variables 不能为空")
        else:
            for index, item in enumerate(variables):
                if not _is_pair(item):
                    report.error(
                        f"节点 `{node_id}` 的 variables[{index}] 必须是 [节点id, 输出名] 二元数组；"
                        "写成 {variable, value_selector} 对象是 0.x/教程写法，1.17 不认"
                    )
        if not data.get("output_type"):
            report.error(f"节点 `{node_id}` 缺少 output_type（string / array[object] / number ...）")
        if "advanced_settings" not in data:
            report.warn(f"节点 `{node_id}` 缺少 advanced_settings")

    elif kind == "http-request":
        for key in ("url", "method"):
            if not data.get(key):
                report.error(f"节点 `{node_id}` (http-request) 缺少 `{key}`")
        auth = data.get("authorization")
        if not isinstance(auth, Mapping) or "type" not in auth:
            report.error(f"节点 `{node_id}` 的 authorization 必须是 {type, config} 对象")
        for key in ("headers", "params"):
            if not isinstance(data.get(key), str):
                report.error(
                    f"节点 `{node_id}` 的 `{key}` 必须是字符串（空也要写 \"\"）；1.17 把 headers/params 列为必填"
                )

    elif kind == "question-classifier":
        classes = data.get("classes")
        if not isinstance(classes, list) or not classes:
            report.error(f"节点 `{node_id}` (question-classifier) 的 classes 不能为空")
        else:
            for index, cls in enumerate(classes):
                if not cls.get("id") or not cls.get("name"):
                    report.error(f"节点 `{node_id}` 的 classes[{index}] 缺少 id 或 name")
        if "categories" in data:
            report.error(f"节点 `{node_id}` 用了 `categories`，1.17 的字段名是 `classes`")

    elif kind == "parameter-extractor":
        if data.get("reasoning_mode") not in ("function_call", "prompt"):
            report.error(f"节点 `{node_id}` 的 reasoning_mode 必须是 function_call 或 prompt")
        if "query_variable_selector" in data and "query" not in data:
            report.error(f"节点 `{node_id}` 用了 `query_variable_selector`，参数提取器的字段名是 `query`")

    elif kind in ("iteration", "loop"):
        if not data.get("start_node_id"):
            report.error(f"节点 `{node_id}` ({kind}) 缺少 start_node_id")


def check_condition(condition: Mapping[str, Any], where: str, report: Report) -> None:
    if not isinstance(condition, Mapping):
        report.error(f"{where} 必须是对象")
        return
    if not condition.get("variable_selector"):
        report.error(f"{where} 缺少 variable_selector")
    operator = condition.get("comparison_operator")
    if operator not in COMPARISON_OPERATORS:
        report.error(f"{where}.comparison_operator={operator!r} 非法")
    if not condition.get("varType"):
        report.warn(f"{where} 缺少 varType（string / number / array[object] ...），前端据此渲染比较控件")


def check_edges(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    report: Report,
) -> None:
    node_types = {n.get("id"): (n.get("data") or {}).get("type") for n in nodes}
    valid_handles: dict[str, set[str]] = {}
    for n in nodes:
        data = n.get("data") or {}
        kind = data.get("type")
        if kind == "if-else":
            valid_handles[n["id"]] = {str(c.get("case_id")) for c in (data.get("cases") or [])} | {"false"}
        elif kind == "question-classifier":
            valid_handles[n["id"]] = {str(c.get("id")) for c in (data.get("classes") or [])}

    for edge in edges:
        edge_id = edge.get("id", "?")
        source, target = edge.get("source"), edge.get("target")
        if source not in node_types:
            report.error(f"边 `{edge_id}` 的 source `{source}` 不存在")
            continue
        if target not in node_types:
            report.error(f"边 `{edge_id}` 的 target `{target}` 不存在")
            continue

        data = edge.get("data") or {}
        if data.get("sourceType") != node_types[source]:
            report.error(
                f"边 `{edge_id}` 的 data.sourceType={data.get('sourceType')!r} "
                f"与源节点实际类型 {node_types[source]!r} 不一致"
            )
        if data.get("targetType") != node_types[target]:
            report.error(
                f"边 `{edge_id}` 的 data.targetType={data.get('targetType')!r} "
                f"与目标节点实际类型 {node_types[target]!r} 不一致"
            )
        for key in ("isInIteration", "isInLoop"):
            if key not in data:
                report.warn(f"边 `{edge_id}` 的 data 缺少 `{key}`")
        for key in ("sourceHandle", "targetHandle"):
            if not edge.get(key):
                report.error(
                    f"边 `{edge_id}` 缺少 `{key}`（1.17 的边必须带 handle，"
                    "普通连线是 source/target，分支边用 case id）"
                )
        if edge.get("type") != "custom":
            report.warn(f"边 `{edge_id}` 的 type 建议为 custom，实际 {edge.get('type')!r}")

        allowed = valid_handles.get(source)
        if allowed is not None and edge.get("sourceHandle") not in allowed:
            report.error(
                f"边 `{edge_id}` 的 sourceHandle={edge.get('sourceHandle')!r} 不是节点 `{source}` 的合法分支；"
                f"允许 {sorted(allowed)}"
            )
        if allowed is None and edge.get("sourceHandle") not in ("source", None):
            report.error(
                f"边 `{edge_id}` 的 sourceHandle 应为 `source`（节点 `{source}` 没有分支），"
                f"实际 {edge.get('sourceHandle')!r}"
            )


def check_references(
    nodes: Sequence[Mapping[str, Any]],
    report: Report,
    env_names: set[str],
    conversation_names: set[str],
) -> set[str]:
    """Resolve every value_selector and {{#node.key#}} reference."""
    outputs = {n.get("id"): declared_outputs(n) for n in nodes}
    node_ids = set(outputs)
    reachable: set[str] = set()

    for node in nodes:
        node_id = node.get("id", "?")
        data = node.get("data") or {}

        for path, selector in list(_iter_selectors(data)) + list(_extra_selectors(data)):
            head, key = selector[0], selector[1]
            if head == "sys":
                if key not in SYS_VARS:
                    report.error(f"节点 `{node_id}` 的 {path} 引用了未知系统变量 `sys.{key}`")
                continue
            if head == "env":
                if key not in env_names:
                    report.error(f"节点 `{node_id}` 的 {path} 引用了未声明的环境变量 `env.{key}`")
                continue
            if head == "conversation":
                if key not in conversation_names:
                    report.error(f"节点 `{node_id}` 的 {path} 引用了未声明的会话变量 `conversation.{key}`")
                continue
            if head not in node_ids:
                report.error(f"节点 `{node_id}` 的 {path} 引用了不存在的节点 `{head}`")
                continue
            reachable.add(head)
            keys = outputs.get(head)
            if keys is None:
                continue  # plugin-defined outputs, cannot verify
            if key not in keys:
                report.error(
                    f"节点 `{node_id}` 的 {path} 引用了 `{head}.{key}`，"
                    f"但 `{head}` ({node_kind(nodes, head)}) 只输出 {sorted(keys) or '（无）'}"
                )

        for text in _iter_text(data):
            for head, key in VAR_REF_RE.findall(text):
                if head == "context":
                    continue  # {{#context#}} is the injected retrieval context
                if head == "sys":
                    if key not in SYS_VARS:
                        report.error(f"节点 `{node_id}` 文本中引用了未知系统变量 `{{{{#sys.{key}#}}}}`")
                    continue
                if head == "env":
                    if key not in env_names:
                        report.error(f"节点 `{node_id}` 文本中引用了未声明的环境变量 `{{{{#env.{key}#}}}}`")
                    continue
                if head == "conversation":
                    continue
                if head not in node_ids:
                    report.error(f"节点 `{node_id}` 文本中引用了不存在的节点 `{{{{#{head}.{key}#}}}}`")
                    continue
                reachable.add(head)
                keys = outputs.get(head)
                if keys is not None and key not in keys:
                    report.error(
                        f"节点 `{node_id}` 文本中引用了 `{head}.{key}`，但 `{head}` 只输出 {sorted(keys) or '（无）'}"
                    )

    return reachable


def node_kind(nodes: Sequence[Mapping[str, Any]], node_id: str) -> str:
    for node in nodes:
        if node.get("id") == node_id:
            return str((node.get("data") or {}).get("type"))
    return "?"


def _iter_text(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_text(item)


def check_reachability(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    report: Report,
) -> None:
    container_ids = {
        n["id"] for n in nodes if (n.get("data") or {}).get("type") in ("iteration", "loop")
    }
    entries = {n["id"] for n in nodes if (n.get("data") or {}).get("type") == "start"}
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])

    walked: set[str] = set()
    frontier = list(entries)
    while frontier:
        current = frontier.pop()
        if current in walked:
            continue
        walked.add(current)
        frontier.extend(adjacency.get(current, ()))

    for node in nodes:
        node_id = node["id"]
        kind = (node.get("data") or {}).get("type")
        if kind in CONTAINER_INNER_TYPES:
            continue
        # Container bodies are reached by the engine from the container's
        # start_node_id, not through a top-level edge, so they are not orphans.
        if node.get("parentId") in container_ids:
            continue
        if node_id not in walked:
            report.warn(f"节点 `{node_id}` ({kind}) 从 start 不可达，永远不会执行")


def check_containers(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]], report: Report) -> None:
    """Iteration/loop must own an inner start sub-node with a wired-up body."""
    by_id = {n.get("id"): n for n in nodes}
    outgoing: dict[str, set[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge["source"], set()).add(edge["target"])

    for node in nodes:
        data = node.get("data") or {}
        kind = data.get("type")
        if kind not in ("iteration", "loop"):
            continue
        node_id = node["id"]
        inner_start = data.get("start_node_id")
        expected = "iteration-start" if kind == "iteration" else "loop-start"
        target = by_id.get(inner_start)
        if target is None:
            report.error(f"节点 `{node_id}` ({kind}) 的 start_node_id=`{inner_start}` 指向不存在的节点")
        else:
            if (target.get("data") or {}).get("type") != expected:
                report.error(
                    f"节点 `{node_id}` ({kind}) 的 start_node_id 应指向一个 `{expected}` 节点，"
                    f"实际是 {(target.get('data') or {}).get('type')!r}"
                )
            if target.get("parentId") != node_id:
                report.warn(
                    f"容器子节点 `{inner_start}` 缺少 parentId={node_id!r}，"
                    "前端无法把它渲染到容器内部"
                )
            if not outgoing.get(inner_start):
                report.error(
                    f"容器子节点 `{inner_start}` 没有任何出边，引擎从 start_node_id 向外展开，"
                    f"容器体不会执行"
                )

        if kind == "loop":
            has_end = any((n.get("data") or {}).get("type") == "loop-end" and n.get("parentId") == node_id for n in nodes)
            if not has_end:
                report.error(f"节点 `{node_id}` (loop) 缺少配套的 `loop-end` 子节点")

        # Body members must be marked, otherwise the frontend scatters them.
        bodies = [
            n for n in nodes
            if n.get("parentId") == node_id and (n.get("data") or {}).get("type") not in CONTAINER_INNER_TYPES
        ]
        if not bodies:
            report.warn(f"节点 `{node_id}` ({kind}) 里没有任何子节点")
        marker = "isInIteration" if kind == "iteration" else "isInLoop"
        for body in bodies:
            if not (body.get("data") or {}).get(marker):
                report.warn(f"容器子节点 `{body['id']}` 的 data 缺少 `{marker}`")


def check_secrets(dsl: Mapping[str, Any], report: Report) -> None:
    for where, text in _walk_strings(dsl):
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                report.error(f"{where} 疑似硬编码了密钥（匹配 {pattern.pattern}）；请改用 {{{{env.XXX}}}}")
                break


def _walk_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path or "<root>", value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")


def check_with_pydantic(nodes: Sequence[Mapping[str, Any]], report: Report, models: Mapping[str, Any]) -> int:
    checked = 0
    for node in nodes:
        data = node.get("data") or {}
        kind = data.get("type")
        model = models.get(kind)
        if model is None:
            continue
        try:
            model.model_validate(dict(data))
            checked += 1
        except Exception as exc:  # noqa: BLE001 - surface the schema error verbatim
            report.error(f"节点 `{node.get('id')}` ({kind}) 未通过 Dify 的 pydantic 模型校验：\n    {str(exc)[:800]}")
    return checked


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def validate_file(path: Path, *, strict: bool = False, deep: bool = True) -> Report:
    report = Report(path)
    try:
        dsl = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        report.error(f"YAML 解析失败：{exc}")
        return report

    if not isinstance(dsl, Mapping):
        report.error("文件内容不是一个 YAML 对象")
        return report

    check_top_level(dsl, report)
    check_variables(dsl, report)

    workflow = dsl.get("workflow") or {}
    graph = workflow.get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        report.error("workflow.graph.nodes 为空")
        return report
    if not isinstance(edges, list):
        report.error("workflow.graph.edges 必须是数组")
        return report
    if "viewport" not in graph:
        report.warn("workflow.graph 缺少 viewport")

    seen_ids: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, Mapping):
            check_node_envelope(node, report, seen_ids)
    for node in nodes:
        if isinstance(node, Mapping):
            check_node_details(node, report)

    check_edges(nodes, edges, report)
    check_containers(nodes, edges, report)

    env_names = {v.get("name") for v in (workflow.get("environment_variables") or []) if isinstance(v, Mapping)}
    conversation_names = {
        v.get("name") for v in (workflow.get("conversation_variables") or []) if isinstance(v, Mapping)
    }
    check_references(nodes, report, env_names, conversation_names)
    check_reachability(nodes, edges, report)

    mode = (dsl.get("app") or {}).get("mode")
    types = [(n.get("data") or {}).get("type") for n in nodes if isinstance(n, Mapping)]
    starts = types.count("start")
    if starts != 1:
        report.error(f"必须恰好有 1 个 start 节点，实际 {starts} 个")
    if mode == "workflow":
        ends = types.count("end")
        if ends != 1:
            report.error(f"workflow 模式必须恰好有 1 个 end 节点，实际 {ends} 个")
    elif mode == "advanced-chat":
        if "answer" not in types:
            report.error("advanced-chat（chatflow）需要至少 1 个 answer 节点，end 不会向前端回复")
        if "end" in types:
            report.warn("advanced-chat 里出现 end 节点；chatflow 的回复出口是 answer")

    check_secrets(dsl, report)

    if deep:
        models = load_pydantic_models()
        if models:
            checked = check_with_pydantic(nodes, report, models)
            report.note(f"已用 Dify 容器内 pydantic 模型深度校验 {checked}/{len(nodes)} 个节点")
        else:
            report.note("未检测到 graphon/core 包，跳过 pydantic 深度校验（只做了信封层语法检查）")

    if strict:
        report.errors.extend(report.warnings)
        report.warnings = []
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Dify 1.17 DSL files")
    parser.add_argument("files", nargs="+", help="DSL YAML file(s)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    parser.add_argument("--shallow", action="store_true", help="skip pydantic validation")
    args = parser.parse_args()

    reports = [validate_file(Path(name), strict=args.strict, deep=not args.shallow) for name in args.files]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "file": r.path,
                        "errors": r.errors,
                        "warnings": r.warnings,
                        "notes": r.notes,
                    }
                    for r in reports
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for report in reports:
            status = "FAIL" if report.errors else ("WARN" if report.warnings else "PASS")
            print(f"[{status}] {report.path}")
            for note in report.notes:
                print(f"  · {note}")
            for message in report.errors:
                print(f"  ERROR {message}")
            for message in report.warnings:
                print(f"  WARN  {message}")

    failed = sum(1 for r in reports if r.errors)
    if not args.json:
        print(f"\n{len(reports) - failed}/{len(reports)} 个文件通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
