#!/usr/bin/env python3
"""Dify 1.17 DSL builder — emits the real export envelope, not the "generic" one.

Why this module exists
----------------------
Dify 1.17's actual export format (`services/app_dsl_service.py`,
`CURRENT_APP_DSL_VERSION = "0.7.0"`) differs from the DSL shape shown in most
tutorials, blog posts, and LLM training data. Hand-writing the envelope is where
nearly every "imports but the canvas is broken" bug comes from, so the envelope
rules live in code here.

Rules encoded (verified against langgenius/dify-api:1.17.0):

* Node top-level ``type`` is ALWAYS ``custom``. The semantic node kind lives in
  ``data.type``. If you write ``type: llm`` at the top level the frontend has no
  renderer for that node and the canvas breaks.
* Top level is ``app`` + ``kind: app`` + ``version`` + ``dependencies``.
  ``kind`` is not ``app-kind``; Dify force-rewrites anything else to ``app``.
* Every node carries id / position / positionAbsolute / selected /
  sourcePosition / targetPosition / width / height, and its ``data`` carries
  type / title / desc / selected.
* Every edge carries source / target / sourceHandle / targetHandle / type /
  zIndex, plus a ``data`` block with isInIteration / isInLoop / sourceType /
  targetType.
* ``environment_variables`` and ``conversation_variables`` entries are keyed by
  ``name`` — NOT ``variable``. The backend factory
  (``factories/variable_factory.py::build_environment_variable_from_mapping``)
  raises ``missing name`` otherwise.
* Node outputs are referenced as ``value_selector: [node_id, output_key]`` in
  node data, and as ``{{#node_id.output_key#}}`` inside prompt text.

Usage::

    from dify_dsl import *

    nodes = [
        start("start", [text_input("topic", "主题")], x=80, y=300),
        llm("llm_1", model=deepseek(), system="...", user="{{#start.topic#}}", x=400, y=300),
        end("end", [out("text", "llm_1", "text")], x=720, y=300),
    ]
    dsl = app_dsl("My Flow", "workflow", nodes=chain(nodes), edges_from=nodes)
    dump(dsl, "my-flow.yml")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - dependency hint
    raise SystemExit("PyYAML is required: pip install pyyaml")

# --------------------------------------------------------------------------
# Registry — every node kind Dify 1.17 recognises (graphon.enums.BuiltinNodeTypes
# plus the three trigger kinds from core.trigger.constants).
# --------------------------------------------------------------------------

BUILTIN_NODE_TYPES = frozenset(
    {
        "start",
        "end",
        "answer",
        "llm",
        "knowledge-retrieval",
        "if-else",
        "code",
        "template-transform",
        "question-classifier",
        "http-request",
        "tool",
        "datasource",
        "variable-aggregator",
        "variable-assigner",  # legacy aggregator, kept for old exports
        "loop",
        "loop-start",
        "loop-end",
        "iteration",
        "iteration-start",
        "parameter-extractor",
        "assigner",
        "document-extractor",
        "list-operator",
        "agent",
        "human-input",
        # trigger kinds
        "trigger-webhook",
        "trigger-schedule",
        "trigger-plugin",
    }
)

#: Node kinds that may only appear as a container's inner start/end.
CONTAINER_INNER_TYPES = frozenset({"iteration-start", "loop-start", "loop-end"})

#: Cosmetic canvas size per node kind (the frontend re-measures on open).
DEFAULT_SIZE: Mapping[str, tuple[int, int]] = {
    "start": (244, 90),
    "end": (244, 140),
    "answer": (244, 105),
    "llm": (244, 200),
    "code": (244, 160),
    "if-else": (244, 140),
    "knowledge-retrieval": (244, 140),
    "variable-aggregator": (244, 110),
    "template-transform": (244, 140),
    "question-classifier": (244, 140),
    "parameter-extractor": (244, 140),
    "http-request": (244, 140),
    "tool": (244, 140),
    "document-extractor": (244, 140),
    "list-operator": (244, 140),
    "iteration": (244, 200),
    "loop": (244, 200),
    "iteration-start": (244, 60),
    "loop-start": (244, 60),
    "loop-end": (244, 60),
    "assigner": (244, 140),
    "agent": (244, 160),
    "human-input": (244, 140),
}

#: Start-node input variable kinds.
START_VAR_TYPES = frozenset(
    {
        "text-input",
        "select",
        "paragraph",
        "number",
        "file",
        "file-list",
        "checkbox",
        "json_object",
        "external_data_tool",
    }
)

#: Environment / conversation variable kinds (graphon.variables.segments.SegmentType).
ENV_VAR_TYPES = frozenset(
    {
        "string",
        "secret",
        "number",
        "integer",
        "float",
        "boolean",
        "object",
        "array[string]",
        "array[number]",
        "array[object]",
        "array[boolean]",
        "array[file]",
        "array[any]",
    }
)

#: The DSL version this module emits. langgenius/dify-api:1.17.0 ships
#: constants/dsl_version.py::CURRENT_APP_DSL_VERSION == "0.7.0". Importing a file
#: whose minor version is lower (e.g. the widely-copied "0.1.5") is accepted but
#: marked COMPLETED_WITH_WARNINGS — and Dify performs NO migration, so the graph
#: must already be structurally correct.
CURRENT_DSL_VERSION = "0.7.0"

#: System variables usable as a selector, e.g. [sys, query]. Not node outputs.
SYS_VARS = frozenset(
    {
        "query",
        "files",
        "conversation_id",
        "user_id",
        "dialogue_count",
        "app_id",
        "workflow_id",
        "workflow_run_id",
        "timestamp",
        "document_id",
        "original_document_id",
        "batch",
        "dataset_id",
        "datasource_type",
        "datasource_info",
        "invoke_from",
    }
)


# --------------------------------------------------------------------------
# Envelope builders
# --------------------------------------------------------------------------


def node(
    node_id: str,
    node_type: str,
    data: Mapping[str, Any] | None = None,
    *,
    title: str = "",
    desc: str = "",
    x: int = 0,
    y: int = 0,
    width: int | None = None,
    height: int | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    """Build one node in the exact 1.17 envelope shape."""
    if node_type not in BUILTIN_NODE_TYPES:
        raise ValueError(f"unknown node type {node_type!r}")
    default_w, default_h = DEFAULT_SIZE.get(node_type, (244, 140))
    return {
        "data": {
            "type": node_type,
            "title": title,
            "desc": desc,
            "selected": selected,
            **dict(data or {}),
        },
        "height": default_h if height is None else height,
        "id": node_id,
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "selected": selected,
        "sourcePosition": "right",
        "targetPosition": "left",
        "type": "custom",
        "width": default_w if width is None else width,
    }


def edge(
    source: str,
    target: str,
    source_type: str,
    target_type: str,
    *,
    source_handle: str = "source",
    target_handle: str = "target",
    edge_id: str | None = None,
    in_iteration: bool = False,
    in_loop: bool = False,
) -> dict[str, Any]:
    """Build one edge. ``source_handle`` carries the branch id for if-else edges."""
    return {
        "data": {
            "isInIteration": in_iteration,
            "isInLoop": in_loop,
            "sourceType": source_type,
            "targetType": target_type,
        },
        "id": edge_id or f"edge-{source}-{target}",
        "source": source,
        "sourceHandle": source_handle,
        "target": target,
        "targetHandle": target_handle,
        "type": "custom",
        "zIndex": 0,
    }


def chain(nodes: Sequence[Mapping[str, Any]], **edge_kwargs: Any) -> list[dict[str, Any]]:
    """Link a linear list of nodes, inferring each edge's types from ``data.type``."""
    edges: list[dict[str, Any]] = []
    for left, right in zip(nodes, nodes[1:]):
        edges.append(
            edge(
                left["id"],
                right["id"],
                left["data"]["type"],
                right["data"]["type"],
                **edge_kwargs,
            )
        )
    return edges


# --------------------------------------------------------------------------
# Node data — start / end / answer
# --------------------------------------------------------------------------


def text_input(variable: str, label: str, *, required: bool = True, max_length: int | None = None) -> dict:
    return {
        "variable": variable,
        "label": label,
        "type": "text-input",
        "required": required,
        "max_length": max_length,
        "options": [],
    }


def paragraph(variable: str, label: str, *, required: bool = True) -> dict:
    return {"variable": variable, "label": label, "type": "paragraph", "required": required, "max_length": None, "options": []}


def number_input(variable: str, label: str, *, required: bool = True) -> dict:
    return {"variable": variable, "label": label, "type": "number", "required": required, "max_length": None, "options": []}


def select_input(variable: str, label: str, options: Sequence[str], *, required: bool = True) -> dict:
    return {
        "variable": variable,
        "label": label,
        "type": "select",
        "required": required,
        "max_length": None,
        "options": list(options),
    }


def file_input(variable: str, label: str, *, extensions: Sequence[str] = (), required: bool = True) -> dict:
    return {
        "variable": variable,
        "label": label,
        "type": "file",
        "required": required,
        "max_length": None,
        "options": [],
        "allowed_file_types": ["document"],
        "allowed_file_extensions": list(extensions) or [".pdf", ".docx", ".txt", ".md"],
        "allowed_file_upload_methods": ["local_file", "remote_url"],
    }


def start(node_id: str, variables: Sequence[Mapping[str, Any]] = (), **kwargs: Any) -> dict:
    """Start node. ``variables: []`` means the app only reads ``sys.query``."""
    return node(node_id, "start", {"variables": list(variables)}, title=kwargs.pop("title", "开始"), **kwargs)


def out(variable: str, node_id: str, output_key: str, value_type: str = "string") -> dict:
    """One ``end`` node output. Mirrors the frontend's output row."""
    return {"variable": variable, "value_type": value_type, "value_selector": [node_id, output_key]}


def end(node_id: str, outputs: Sequence[Mapping[str, Any]] = (), **kwargs: Any) -> dict:
    return node(node_id, "end", {"outputs": list(outputs)}, title=kwargs.pop("title", "结束"), **kwargs)


def answer(node_id: str, text: str, **kwargs: Any) -> dict:
    """Chatflow terminal node. Use this (not ``end``) in advanced-chat apps."""
    return node(node_id, "answer", {"answer": text, "variables": []}, title=kwargs.pop("title", "直接回复"), **kwargs)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

#: Shipped model names per provider. Dify passes unknown names straight through
#: WITHOUT normalising completion params — a misspelled model often means
#: provider-side defaults leak in (DeepSeek, for example, silently turns thinking
#: mode back on and floods `llm.text` with a <think> chain). Always use a name the
#: plugin actually declares.
MODEL_PRESETS: Mapping[str, tuple[str, str]] = {
    "deepseek-chat": ("langgenius/deepseek/deepseek", "deepseek-chat"),
    "deepseek-flash": ("langgenius/deepseek/deepseek", "deepseek-v4-flash"),
    "deepseek-pro": ("langgenius/deepseek/deepseek", "deepseek-v4-pro"),
    "gpt-4o": ("langgenius/openai/openai", "gpt-4o"),
    "gpt-4o-mini": ("langgenius/openai/openai", "gpt-4o-mini"),
    "claude-sonnet": ("langgenius/anthropic/anthropic", "claude-sonnet-4-6"),
    "claude-opus": ("langgenius/anthropic/anthropic", "claude-opus-4-8"),
    "qwen-max": ("langgenius/tongyi/tongyi", "qwen-max"),
    "ollama": ("langgenius/ollama/ollama", "qwen2.5:7b"),
}


def model_config(
    provider: str,
    name: str,
    *,
    mode: str = "chat",
    completion_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "name": name,
        "mode": mode,
        "completion_params": dict(completion_params or {}),
    }


def deepseek(
    name: str = "deepseek-v4-flash",
    *,
    temperature: float = 0.2,
    max_tokens: int = 2048,
    json_object: bool = False,
) -> dict[str, Any]:
    """DeepSeek preset with thinking mode explicitly disabled."""
    params: dict[str, Any] = {
        "thinking": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_object:
        params["response_format"] = "json_object"
    return model_config("langgenius/deepseek/deepseek", name, completion_params=params)


def openai(name: str = "gpt-4o", *, temperature: float = 0.3, max_tokens: int = 2048, json_object: bool = False) -> dict:
    params: dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens, "top_p": 1}
    if json_object:
        params["response_format"] = "json_object"
    return model_config("langgenius/openai/openai", name, completion_params=params)


def ollama(name: str = "qwen2.5:7b", *, temperature: float = 0.3, max_tokens: int = 2048) -> dict:
    return model_config("langgenius/ollama/ollama", name, completion_params={"temperature": temperature, "max_tokens": max_tokens})


# --------------------------------------------------------------------------
# Node data — llm
# --------------------------------------------------------------------------


def _retry_config() -> dict[str, Any]:
    """Frontend-shaped retry block (matches langgenius/dify-web 1.17 exports).

    The backend model is ``RetryConfig(retry_enabled, max_retries, retry_interval)``
    and node data allows extra keys, so this block validates and leaves retries
    off. Keep ``enabled: false`` unless you actually want retries.
    """
    return {
        "enabled": False,
        "exponential_backoff": {
            "enabled": False,
            "max_interval": 10000,
            "multiplier": 2,
        },
        "max_retries": 1,
        "retry_interval": 1000,
    }


def llm(
    node_id: str,
    *,
    model: Mapping[str, Any],
    system: str = "",
    user: str = "",
    context_selector: Sequence[str] | None = None,
    memory: bool = False,
    memory_window: int = 10,
    memory_query: str = "{{#sys.query#}}",
    vision: bool = False,
    structured_output: bool = False,
    reasoning_format: str = "tagged",
    **kwargs: Any,
) -> dict:
    """LLM node.

    ``context_selector`` attaches retrieval results, e.g. ``["retriever", "result"]``;
    reference them inside prompts as ``{{#context#}}``. ``memory`` needs a chatflow
    (and ``sys.query``), so it defaults off for single-shot workflows.
    """
    template: list[dict[str, str]] = []
    if system:
        template.append({"role": "system", "text": system})
    if user:
        template.append({"role": "user", "text": user})
    return node(
        node_id,
        "llm",
        {
            "model": dict(model),
            "prompt_template": template,
            "context": {"enabled": context_selector is not None, "variable_selector": list(context_selector or [])},
            "vision": {"enabled": vision, "configs": {"variable_selector": []}},
            "memory": {
                "query_prompt_template": memory_query,
                "window": {"enabled": memory, "size": memory_window},
            },
            "structured_output": {"enabled": structured_output},
            "reasoning_format": reasoning_format,
            "retry_config": _retry_config(),
        },
        **kwargs,
    )


# --------------------------------------------------------------------------
# Node data — code / template-transform
# --------------------------------------------------------------------------


def code(
    node_id: str,
    *,
    code_text: str,
    variables: Mapping[str, Sequence[str]],
    outputs: Mapping[str, str] | Sequence[str],
    code_language: str = "python3",
    dependencies: Sequence[Mapping[str, str]] = (),
    **kwargs: Any,
) -> dict:
    """Code node.

    ``variables`` maps the function parameter name to its selector, e.g.
    ``{"llm_output": ["llm_1", "text"]}``. ``outputs`` maps the returned dict's key
    to a SegmentType (``string`` / ``number`` / ``object`` / ``array[object]`` ...).
    The entrypoint must be ``main(...) -> dict``.

    Note the field name is ``code_language`` — writing ``language`` is silently
    ignored and the node falls back to python3.
    """
    if not isinstance(outputs, Mapping):
        outputs = {key: "string" for key in outputs}
    data: dict[str, Any] = {
        "code": code_text,
        "code_language": code_language,
        "variables": [{"variable": name, "value_selector": list(sel)} for name, sel in variables.items()],
        "outputs": {name: {"children": None, "type": seg} for name, seg in outputs.items()},
    }
    if dependencies:
        # Third-party wheels must be allow-listed in the sandbox and pinned here.
        data["dependencies"] = [dict(d) for d in dependencies]
    return node(node_id, "code", data, **kwargs)


def template_transform(
    node_id: str,
    *,
    template: str,
    variables: Mapping[str, Sequence[str]],
    **kwargs: Any,
) -> dict:
    """Jinja2 string assembly. Output key is always ``output``."""
    return node(
        node_id,
        "template-transform",
        {
            "template": template,
            "variables": [{"variable": name, "value_selector": list(sel)} for name, sel in variables.items()],
        },
        **kwargs,
    )


def document_extractor(node_id: str, *, variable_selector: Sequence[str], **kwargs: Any) -> dict:
    """Extract text from an uploaded file. Output key is ``text``."""
    return node(node_id, "document-extractor", {"variable_selector": list(variable_selector)}, **kwargs)


# --------------------------------------------------------------------------
# Node data — branching
# --------------------------------------------------------------------------


def condition(
    left: Sequence[str],
    operator: str,
    value: Any = None,
    *,
    var_type: str = "string",
    condition_id: str | None = None,
) -> dict:
    """One if-else condition.

    ``operator`` accepts ``is`` / ``is not`` / ``contains`` / ``not contains`` /
    ``start with`` / ``ends with`` / ``empty`` / ``not empty`` / ``=`` / ``≠`` /
    ``>`` / ``<`` / ``≥`` / ``≤`` / ``is null`` / ``is not null``.
    """
    payload: dict[str, Any] = {
        "id": condition_id or f"cond-{'-'.join(left)}",
        "varType": var_type,
        "variable_selector": list(left),
        "comparison_operator": operator,
    }
    if value is not None:
        payload["value"] = value
    return payload


def if_else(
    node_id: str,
    *,
    cases: Sequence[tuple[str, str, Sequence[Mapping[str, Any]]]],
    logical_operator: str = "and",
    **kwargs: Any,
) -> dict:
    """If-else node.

    ``cases`` is a list of ``(case_id, logical_operator, conditions)``. Every case
    id becomes an outgoing ``sourceHandle``; the implicit else branch uses
    ``"false"``. Each case also needs its own top-level ``id`` equal to the
    case id — the runtime matches on it.
    """
    return node(
        node_id,
        "if-else",
        {
            "logical_operator": logical_operator,
            "cases": [
                {
                    "case_id": case_id,
                    "id": case_id,
                    "logical_operator": case_operator,
                    "conditions": [dict(c) for c in conditions],
                }
                for case_id, case_operator, conditions in cases
            ],
        },
        **kwargs,
    )


def question_classifier(
    node_id: str,
    *,
    model: Mapping[str, Any],
    classes: Sequence[tuple[str, str]],
    query_selector: Sequence[str] = ("sys", "query"),
    instruction: str = "",
    memory: bool = False,
    **kwargs: Any,
) -> dict:
    """Intent router. ``classes`` is a list of ``(class_id, name)``.

    Each class id becomes an outgoing ``sourceHandle``. The field is ``classes``
    with entries ``{id, name, label}`` — ``categories`` is not a Dify field.
    """
    return node(
        node_id,
        "question-classifier",
        {
            "query_variable_selector": list(query_selector),
            "model": dict(model),
            "classes": [{"id": class_id, "name": name, "label": name} for class_id, name in classes],
            "instruction": instruction,
            "memory": {"query_prompt_template": "{{#sys.query#}}", "window": {"enabled": memory, "size": 10}},
            "vision": {"enabled": False, "configs": {"variable_selector": []}},
        },
        **kwargs,
    )


# --------------------------------------------------------------------------
# Node data — retrieval / aggregation
# --------------------------------------------------------------------------


def knowledge_retrieval(
    node_id: str,
    *,
    query_selector: Sequence[str],
    dataset_ids: Sequence[str] = (),
    top_k: int = 5,
    score_threshold: float | None = None,
    reranking_enable: bool = True,
    reranking_provider: str = "",
    reranking_model: str = "",
    retrieval_mode: str = "multiple",
    **kwargs: Any,
) -> dict:
    """Knowledge retrieval.

    Output key is ``result``. ``dataset_ids`` are dataset UUIDs; leaving the list
    empty is legal and means "bind in the UI after import". Reranking needs a
    reranker model configured in the workspace (SiliconFlow
    ``BAAI/bge-reranker-v2-m3`` works well for Chinese corpora).
    """
    return node(
        node_id,
        "knowledge-retrieval",
        {
            "query_variable_selector": list(query_selector),
            "dataset_ids": list(dataset_ids),
            "retrieval_mode": retrieval_mode,
            "multiple_retrieval_config": {
                "top_k": top_k,
                "score_threshold": score_threshold,
                "reranking_enable": reranking_enable,
                "reranking_mode": "reranking_model",
                "reranking_model": {"provider": reranking_provider, "model": reranking_model},
                "weights": None,
            },
            "metadata_filtering_mode": "disabled",
            "vision": {"enabled": False, "configs": {"variable_selector": []}},
        },
        **kwargs,
    )


def variable_aggregator(
    node_id: str,
    *,
    variables: Sequence[Sequence[str]],
    output_type: str = "string",
    **kwargs: Any,
) -> dict:
    """Merge branch outputs.

    ``variables`` is a list of ``[node_id, output_key]`` PAIRS — not objects.
    Order matters: the aggregator returns the FIRST NON-EMPTY value, and ``[]``
    (an empty array) counts as non-empty. Put branch-specific sources ahead of
    anything that always runs, or a legitimately empty later value gets masked.
    """
    return node(
        node_id,
        "variable-aggregator",
        {
            "output_type": output_type,
            "variables": [list(v) for v in variables],
            "advanced_settings": {"group_enabled": False, "groups": []},
        },
        **kwargs,
    )


def assigner(
    node_id: str,
    *,
    items: Sequence[Mapping[str, Any]],
    **kwargs: Any,
) -> dict:
    """Conversation / environment variable writer (node type ``assigner``).

    Each item is ``{variable_selector, input_type, operation, value}``, e.g.::

        {"variable_selector": ["conversation", "user_name"],
         "input_type": "variable", "operation": "overwrite",
         "value": ["start", "name"]}
    """
    return node(node_id, "assigner", {"items": [dict(i) for i in items]}, **kwargs)


# --------------------------------------------------------------------------
# Node data — external calls
# --------------------------------------------------------------------------


def http_request(
    node_id: str,
    *,
    url: str,
    method: str = "post",
    body: Mapping[str, Any] | None = None,
    headers: str = "",
    params: str = "",
    auth_type: str = "no-auth",
    auth_config: Mapping[str, Any] | None = None,
    timeout: Mapping[str, int] | None = None,
    **kwargs: Any,
) -> dict:
    """HTTP request node.

    ``url`` / ``method`` / ``authorization`` / ``headers`` / ``params`` are all
    required by the 1.17 model — omitting ``headers`` or ``params`` fails
    validation. Never inline a credential: put it in ``headers`` as
    ``Authorization: Bearer {{env.MY_TOKEN}}`` and declare the env var.

    Outputs: ``body``, ``status_code``, ``headers``, ``files``.
    """
    payload: dict[str, Any] = {
        "method": method,
        "url": url,
        "authorization": {"type": auth_type, "config": dict(auth_config) if auth_config else None},
        "headers": headers,
        "params": params,
    }
    if body is not None:
        payload["body"] = dict(body)
    if timeout is not None:
        payload["timeout"] = dict(timeout)
    return node(node_id, "http-request", payload, **kwargs)


def json_body(data: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """JSON request body from ``{key, value, type}`` rows (``type`` usually ``text``)."""
    return {"type": "json", "data": [dict(row) for row in data]}


def raw_text_body(text: str) -> dict[str, Any]:
    return {"type": "raw-text", "data": [{"key": "", "value": text, "type": "text"}]}


def tool(
    node_id: str,
    *,
    provider_id: str,
    provider_name: str,
    provider_type: str,
    tool_name: str,
    tool_label: str,
    parameters: Mapping[str, Mapping[str, Any]],
    tool_configurations: Mapping[str, Any] | None = None,
    credential_id: str | None = None,
    plugin_unique_identifier: str | None = None,
    **kwargs: Any,
) -> dict:
    """Tool node — calls one tool from an installed plugin.

    Parameters come in two halves: ``tool_parameters`` holds the per-call inputs
    (``{"type": "variable"|"constant"|"mixed", "value": ...}``), while
    ``tool_configurations`` holds the tool's provider-side settings. Both are
    required, and ``credential_id`` must point at a credential configured in the
    workspace.
    """
    payload: dict[str, Any] = {
        "provider_id": provider_id,
        "provider_type": provider_type,
        "provider_name": provider_name,
        "tool_name": tool_name,
        "tool_label": tool_label,
        "tool_configurations": dict(tool_configurations or {}),
        "tool_parameters": {k: dict(v) for k, v in parameters.items()},
    }
    if credential_id is not None:
        payload["credential_id"] = credential_id
    if plugin_unique_identifier is not None:
        payload["plugin_unique_identifier"] = plugin_unique_identifier
    return node(node_id, "tool", payload, **kwargs)


def agent(
    node_id,
    *,
    strategy_provider: str = "langgenius/agent/agent",
    strategy_name: str = "ReAct",
    strategy_label: str = "",
    parameters: Mapping[str, Mapping[str, Any]] | None = None,
    memory: bool = False,
    **kwargs: Any,
) -> dict:
    """Agent node driven by a plugin-provided strategy.

    ``agent_strategy_name`` must match a strategy the installed agent plugin
    actually declares (``ReAct`` / ``FunctionCalling`` for langgenius/agent).
    If the plugin is missing the node imports as a dead node — this builder cannot
    verify that for you, so check the workspace before shipping an agent app.
    """
    return node(
        node_id,
        "agent",
        {
            "agent_strategy_provider_name": strategy_provider,
            "agent_strategy_name": strategy_name,
            "agent_strategy_label": strategy_label or strategy_name,
            "agent_parameters": {
                key: dict(value) for key, value in (parameters or default_agent_parameters()).items()
            },
            "memory": {"query_prompt_template": "{{#sys.query#}}", "window": {"enabled": memory, "size": 10}},
        },
        **kwargs,
    )


def default_agent_parameters(
    *,
    model: Mapping[str, Any] | None = None,
    instruction: str = "Use the available tools to answer accurately.",
    tools: Sequence[Mapping[str, Any]] = (),
    maximum_iterations: int = 10,
    query: Sequence[str] = ("sys", "query"),
) -> dict[str, Mapping[str, Any]]:
    return {
        "model": {"type": "constant", "value": dict(model or deepseek())},
        "tools": {"type": "constant", "value": [dict(t) for t in tools]},
        "instruction": {"type": "mixed", "value": instruction},
        "query": {"type": "mixed", "value": ""},
        "maximum_iterations": {"type": "constant", "value": maximum_iterations},
    }


# --------------------------------------------------------------------------
# Node data — structured extraction
# --------------------------------------------------------------------------


def parameter_extractor(
    node_id: str,
    *,
    model: Mapping[str, Any],
    query_selector: Sequence[str],
    parameters: Sequence[Mapping[str, Any]],
    instruction: str = "",
    reasoning_mode: str = "prompt",
    memory: bool = False,
    **kwargs: Any,
) -> dict:
    """LLM-backed structured extraction.

    The query field is ``query`` (a selector), not ``query_variable_selector``.
    Each parameter is ``{name, type, description, required, options}`` where
    ``type`` is one of ``string`` / ``number`` / ``select`` / ``array[string]`` /
    ``array[number]`` / ``array[object]`` / ``array[boolean]``.
    """
    return node(
        node_id,
        "parameter-extractor",
        {
            "model": dict(model),
            "query": list(query_selector),
            "parameters": [dict(p) for p in parameters],
            "instruction": instruction,
            "reasoning_mode": reasoning_mode,
            "memory": {"query_prompt_template": "{{#sys.query#}}", "window": {"enabled": memory, "size": 10}},
            "vision": {"enabled": False, "configs": {"variable_selector": []}},
        },
        **kwargs,
    )


def extract_param(
    name: str,
    *,
    description: str,
    param_type: str = "string",
    required: bool = True,
    options: Sequence[str] | None = None,
) -> dict:
    return {
        "name": name,
        "type": param_type,
        "description": description,
        "required": required,
        "options": list(options) if options else None,
    }


# --------------------------------------------------------------------------
# Node data — list operator / iteration / loop
# --------------------------------------------------------------------------


def list_operator(
    node_id: str,
    *,
    variable: Sequence[str],
    extract_serial: str = "1",
    filter_conditions: Sequence[Mapping[str, Any]] = (),
    order_key: str = "",
    order: str = "asc",
    limit_size: int = -1,
    **kwargs: Any,
) -> dict:
    """Filter / sort / slice / pick-one from an array. Output key is ``result``."""
    return node(
        node_id,
        "list-operator",
        {
            "variable": list(variable),
            "filter_by": {"enabled": bool(filter_conditions), "conditions": [dict(c) for c in filter_conditions]},
            "order_by": {"enabled": bool(order_key), "key": order_key, "value": order},
            "limit": {"enabled": limit_size > 0, "size": limit_size},
            "extract_by": {"enabled": True, "serial": extract_serial},
        },
        **kwargs,
    )


def iteration(
    node_id,
    *,
    start_node_id: str,
    iterator_selector: Sequence[str],
    output_selector: Sequence[str],
    is_parallel: bool = False,
    parallel_nums: int = 10,
    error_handle_mode: str = "terminated",
    flatten_output: bool = True,
    **kwargs: Any,
) -> dict:
    """Iteration container.

    The container needs an inner ``iteration-start`` node whose id is
    ``start_node_id``; inner nodes and inner edges carry ``isInIteration: true``.
    Inside, read the current element as ``{{#<iteration_id>.item#}}``.
    Outputs: ``output`` (collected results), ``item``, ``index``.
    """
    return node(
        node_id,
        "iteration",
        {
            "start_node_id": start_node_id,
            "iterator_selector": list(iterator_selector),
            "output_selector": list(output_selector),
            "is_parallel": is_parallel,
            "parallel_nums": parallel_nums,
            "error_handle_mode": error_handle_mode,
            "flatten_output": flatten_output,
        },
        **kwargs,
    )


def loop(
    node_id,
    *,
    start_node_id: str,
    loop_count: int = 10,
    break_conditions: Sequence[Mapping[str, Any]] = (),
    logical_operator: str = "and",
    loop_variables: Sequence[Mapping[str, Any]] = (),
    **kwargs: Any,
) -> dict:
    """Retry-until-condition container. Needs an inner 'loop-start' and 'loop-end'."""
    return node(
        node_id,
        "loop",
        {
            "start_node_id": start_node_id,
            "loop_count": loop_count,
            "break_conditions": [dict(c) for c in break_conditions],
            "logical_operator": logical_operator,
            "loop_variables": [dict(v) for v in loop_variables],
        },
        **kwargs,
    )


def loop_variable(name: str, selector: Sequence[str], *, var_type: str = "string") -> dict:
    return {"label": name, "var_type": var_type, "value_type": "variable", "value": list(selector)}


# --------------------------------------------------------------------------
# Container nodes — iteration / loop
# --------------------------------------------------------------------------

#: ReactFlow node type the frontend renders container sub-nodes with. The main
#: nodes all use ``custom`` + ``data.type``; container bookkeeping nodes have
#: their own renderer keys, matching langgenius/dify's own graph generator
#: (``core/workflow/generator/runner.py``).
CONTAINER_INNER_RENDERERS: Mapping[str, str] = {
    "iteration-start": "custom-iteration-start",
    "loop-start": "custom-loop-start",
    "loop-end": "custom-loop-end",
}


def _inner_node(
    inner_id: str,
    inner_type: str,
    parent_id: str,
    *,
    x: int,
    y: int,
    marker: str,
) -> dict[str, Any]:
    return {
        "data": {
            "type": inner_type,
            "title": "",
            "desc": "",
            "selected": False,
            marker: True,
        },
        "draggable": False,
        "extent": "parent",
        "id": inner_id,
        "parentId": parent_id,
        "position": {"x": x, "y": y},
        "selectable": False,
        "type": CONTAINER_INNER_RENDERERS[inner_type],
        "zIndex": 1002,
    }


def _child_marker(child: dict[str, Any], container_id: str, kind: str) -> dict[str, Any]:
    """Mark a node as living inside a container (what the frontend reads)."""
    child["parentId"] = container_id
    if kind == "iteration":
        child["data"].setdefault("isInIteration", True)
        child["data"].setdefault("iteration_id", container_id)
    else:
        child["data"].setdefault("isInLoop", True)
        child["data"].setdefault("loop_id", container_id)
    return child


def iteration_container(
    node_id: str,
    *,
    iterator_selector: Sequence[str],
    output_selector: Sequence[str],
    x: int,
    y: int,
    is_parallel: bool = False,
    parallel_nums: int = 10,
    error_handle_mode: str = "terminated",
    flatten_output: bool = True,
    title: str = "迭代",
) -> list[dict[str, Any]]:
    """Build an iteration container and its inner start node.

    Returns ``[container, inner_start]``. Add your body nodes with
    :func:`in_container` and wire the body with :func:`inner_edge` — the engine
    expands the container by walking outward from ``start_node_id``, so the inner
    start must have a real edge to the first body node.

    Inside the body, read the current element as ``{{#<iteration_id>.item#}}``.
    """
    start_id = f"{node_id}start"
    container = node(
        node_id,
        "iteration",
        {
            "start_node_id": start_id,
            "iterator_selector": list(iterator_selector),
            "output_selector": list(output_selector),
            "is_parallel": is_parallel,
            "parallel_nums": parallel_nums,
            "error_handle_mode": error_handle_mode,
            "flatten_output": flatten_output,
        },
        title=title,
        x=x,
        y=y,
        width=808,
        height=204,
    )
    container["zIndex"] = 1
    return [container, _inner_node(start_id, "iteration-start", node_id, x=x + 60, y=y + 78, marker="isInIteration")]


def loop_container(
    node_id: str,
    *,
    loop_count: int = 10,
    break_conditions: Sequence[Mapping[str, Any]] = (),
    logical_operator: str = "and",
    loop_variables: Sequence[Mapping[str, Any]] = (),
    x: int,
    y: int,
    title: str = "循环",
) -> list[dict[str, Any]]:
    """Build a loop container with its inner start and end nodes.

    A loop needs both a ``loop-start`` and a ``loop-end`` child; the body edges run
    start → ... → end and the exit condition is evaluated between rounds.
    """
    start_id = f"{node_id}start"
    end_id = f"{node_id}end"
    container = node(
        node_id,
        "loop",
        {
            "start_node_id": start_id,
            "loop_count": loop_count,
            "break_conditions": [dict(c) for c in break_conditions],
            "logical_operator": logical_operator,
            "loop_variables": [dict(v) for v in loop_variables],
        },
        title=title,
        x=x,
        y=y,
        width=808,
        height=204,
    )
    container["zIndex"] = 1
    return [
        container,
        _inner_node(start_id, "loop-start", node_id, x=x + 60, y=y + 78, marker="isInLoop"),
        _inner_node(end_id, "loop-end", node_id, x=x + 620, y=y + 78, marker="isInLoop"),
    ]


def in_container(child: Mapping[str, Any], container_id: str, kind: str) -> dict[str, Any]:
    """Mark an existing node as a container body member."""
    return _child_marker(dict(child), container_id, kind)


def inner_edge(
    source: str,
    target: str,
    source_type: str,
    target_type: str,
    *,
    kind: str = "iteration",
    **kwargs: Any,
) -> dict[str, Any]:
    """An edge inside a container body (sets the isInIteration/isInLoop flag)."""
    if kind == "iteration":
        return edge(source, target, source_type, target_type, in_iteration=True, **kwargs)
    return edge(source, target, source_type, target_type, in_loop=True, **kwargs)


# --------------------------------------------------------------------------
# App assembly
# --------------------------------------------------------------------------


def default_features(*, chat: bool = False, opening_statement: str = "", suggested_questions: Sequence[str] = ()) -> dict:
    """The full ``workflow.features`` block the 1.17 frontend writes.

    ``retriever_resource.enabled`` must be true for chat apps that should show
    citation cards next to the answer — it is a separate switch from the
    knowledge-retrieval node itself.
    """
    return {
        "file_upload": {
            "enabled": False,
            "allowed_file_extensions": [],
            "allowed_file_types": [],
            "allowed_file_upload_methods": [],
            "number_limits": 3,
            "fileUploadConfig": {
                "audio_file_size_limit": 50,
                "batch_count_limit": 5,
                "file_size_limit": 15,
                "image_file_size_limit": 10,
                "video_file_size_limit": 100,
                "workflow_file_upload_limit": 10,
            },
            "image": {"enabled": False, "number_limits": 3, "transfer_methods": ["local_file", "remote_url"]},
        },
        "opening_statement": opening_statement,
        "retriever_resource": {"enabled": bool(chat)},
        "sensitive_word_avoidance": {"enabled": False},
        "speech_to_text": {"enabled": False},
        "suggested_questions": list(suggested_questions),
        "suggested_questions_after_answer": {"enabled": bool(chat)},
        "text_to_speech": {"enabled": False, "language": "", "voice": ""},
    }


def env_var(name: str, value: Any = "", value_type: str = "string", description: str = "") -> dict:
    """Environment variable. Keyed by ``name`` — ``variable`` is rejected on import."""
    payload: dict[str, Any] = {"name": name, "value": value, "value_type": value_type}
    if description:
        payload["description"] = description
    return payload


def conversation_var(name: str, value: Any = "", value_type: str = "string", description: str = "") -> dict:
    """Conversation variable (chatflow only). Also keyed by ``name``."""
    return env_var(name, value, value_type, description)


def app_dsl(
    name: str,
    mode: str,
    *,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    description: str = "",
    icon: str = "🤖",
    icon_background: str = "#FFEAD5",
    icon_type: str = "emoji",
    use_icon_as_answer_icon: bool = False,
    features: Mapping[str, Any] | None = None,
    environment_variables: Sequence[Mapping[str, Any]] = (),
    conversation_variables: Sequence[Mapping[str, Any]] = (),
    dependencies: Sequence[Mapping[str, Any]] = (),
    zoom: float = 0.7,
    version: str = CURRENT_DSL_VERSION,
) -> dict[str, Any]:
    """Assemble a complete DSL document.

    ``mode`` is ``workflow`` / ``advanced-chat`` (chatflow) / ``completion`` /
    ``chat`` / ``agent-chat``. Workflows end with an ``end`` node; chatflows end
    with an ``answer`` node.
    """
    return {
        "app": {
            "description": description,
            "icon": icon,
            "icon_type": icon_type,
            "icon_background": icon_background,
            "mode": mode,
            "name": name,
            "use_icon_as_answer_icon": use_icon_as_answer_icon,
        },
        "dependencies": list(dependencies),
        "kind": "app",
        "version": version,
        "workflow": {
            "conversation_variables": list(conversation_variables),
            "environment_variables": list(environment_variables),
            "features": dict(features) if features is not None else default_features(chat=mode == "advanced-chat"),
            "graph": {
                "edges": list(edges),
                "nodes": list(nodes),
                "viewport": {"x": 0, "y": 0, "zoom": zoom},
            },
        },
    }


def dump(dsl: Mapping[str, Any], path: str | Path) -> Path:
    """Write canonical DSL YAML (unicode preserved, key order preserved)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(dict(dsl), allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096),
        encoding="utf-8",
    )
    return target
