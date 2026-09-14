#!/usr/bin/env python3
"""Regenerate every shipped template and example from ``dify_dsl`` definitions.

The YAML under ``templates/`` and ``examples/`` is generated, not hand-written —
hand-writing node envelopes is exactly how the old version of this skill produced
DSL that Dify accepted but rendered as broken canvas nodes.

Run after editing this file::

    python scripts/build_templates.py            # write templates/ + examples/
    python scripts/build_templates.py --check     # fail if outputs are stale

Then validate in Dify::

    bash scripts/validate.sh
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dify_dsl import (  # noqa: E402
    agent,
    answer,
    app_dsl,
    code,
    condition,
    conversation_var,
    default_features,
    deepseek,
    document_extractor,
    dump,
    edge,
    end,
    env_var,
    extract_param,
    file_input,
    http_request,
    if_else,
    in_container,
    inner_edge,
    iteration_container,
    json_body,
    knowledge_retrieval,
    llm,
    node,
    number_input,
    openai,
    out,
    paragraph,
    parameter_extractor,
    question_classifier,
    select_input,
    start,
    template_transform,
    text_input,
    variable_aggregator,
)

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
EXAMPLES_DIR = SKILL_DIR / "examples"

GENERATED: dict[Path, dict[str, Any]] = {}


def emit(path: Path, dsl: dict[str, Any]) -> None:
    GENERATED[path] = dsl


# ==========================================================================
# 1. chatflow-basic — single LLM call with conversation memory
# ==========================================================================


def build_chatflow_basic() -> dict[str, Any]:
    nodes = [
        start("start", [], x=80, y=300),
        llm(
            "llm_chat",
            model=openai("gpt-4o-mini", temperature=0.6, max_tokens=1500),
            system=(
                "You are a concise, friendly assistant.\n"
                "Rules:\n"
                "- Answer in the user's language.\n"
                "- Keep replies under 150 words unless asked for detail.\n"
                "- Say so plainly when you do not know something."
            ),
            user="{{#sys.query#}}",
            memory=True,
            memory_window=10,
            x=400,
            y=300,
            title="LLM 回答",
        ),
        answer("answer", "{{#llm_chat.text#}}", x=760, y=300),
    ]
    edges = [
        edge("start", "llm_chat", "start", "llm"),
        edge("llm_chat", "answer", "llm", "answer"),
    ]
    return app_dsl(
        "Basic Chatflow",
        "advanced-chat",
        nodes=nodes,
        edges=edges,
        description="Single-LLM chatflow with 10-turn conversation memory.",
        icon="💬",
        icon_background="#E8FFD5",
        features=default_features(
            chat=True,
            opening_statement="Hi! What can I help you with?",
            suggested_questions=["Summarise this week's priorities", "Draft a short reply to a customer"],
        ),
    )


# ==========================================================================
# 2. rag-qa — retrieval-augmented chatflow with citation cards
# ==========================================================================


def build_rag_qa() -> dict[str, Any]:
    nodes = [
        start("start", [], x=80, y=300),
        knowledge_retrieval(
            "retriever",
            query_selector=["sys", "query"],
            top_k=5,
            reranking_enable=True,
            x=400,
            y=300,
            title="知识检索",
        ),
        llm(
            "llm_answer",
            model=openai("gpt-4o", temperature=0.3, max_tokens=1500),
            system=(
                "Answer using ONLY the provided context.\n"
                "Rules:\n"
                "- Cite sources inline as [Source N].\n"
                "- If the context does not contain the answer, reply exactly: "
                "\"I don't have that information in my knowledge base.\"\n"
                "- Never invent policy numbers, dates, or figures."
            ),
            user="Context:\n{{#context#}}\n\nQuestion:\n{{#sys.query#}}",
            context_selector=["retriever", "result"],
            memory=True,
            memory_window=10,
            x=760,
            y=300,
            title="LLM 回答",
        ),
        answer("answer", "{{#llm_answer.text#}}", x=1120, y=300),
    ]
    edges = [
        edge("start", "retriever", "start", "knowledge-retrieval"),
        edge("retriever", "llm_answer", "knowledge-retrieval", "llm"),
        edge("llm_answer", "answer", "llm", "answer"),
    ]
    return app_dsl(
        "Doc Q&A Chatflow",
        "advanced-chat",
        nodes=nodes,
        edges=edges,
        description="Retrieval-augmented Q&A over a Dify knowledge base, with citation cards.",
        icon="📚",
        icon_background="#E8FFD5",
        features=default_features(
            chat=True,
            opening_statement="Ask me anything about our internal documents.",
            suggested_questions=["What is the travel expense limit?", "How do I request annual leave?"],
        ),
    )


# ==========================================================================
# 3. workflow-branching — classify then route to different prompts
# ==========================================================================

BRANCH_PARSE_CODE = '''import json
import re


THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _extract(text: str) -> dict:
    """Pull the last JSON object that mentions `route` out of the model output.

    Scanning backwards matters: a reasoning model often echoes a sample object in
    its thinking block, and taking the first brace pair would grab that example
    instead of the real answer.
    """
    text = THINK_RE.sub("", text or "")
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    for start in reversed(starts):
        depth, in_str, escape = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(text[start:i + 1])
                    except Exception:
                        break
                    if isinstance(data, dict) and "route" in data:
                        return data
                    break
    return {}


def main(llm_output: str) -> dict:
    data = _extract(llm_output)
    route = str(data.get("route") or "").strip().lower()
    if route not in ("premium", "standard"):
        route = "standard"
    return {"route": route, "reason": str(data.get("reason") or "")}
'''


def build_workflow_branching() -> dict[str, Any]:
    nodes = [
        start("start", [paragraph("request", "Customer request")], x=80, y=300),
        llm(
            "llm_classify",
            model=openai("gpt-4o-mini", temperature=0.1, max_tokens=256, json_object=True),
            system=(
                "Classify the customer request into exactly one route.\n"
                "premium = enterprise contract, SLA, or security review.\n"
                "standard = everything else.\n"
                'Reply with JSON only: {"route": "premium"|"standard", "reason": "<10 words>"}'
            ),
            user="{{#start.request#}}",
            x=400,
            y=300,
            title="LLM 分类",
        ),
        code(
            "code_parse",
            code_text=BRANCH_PARSE_CODE,
            variables={"llm_output": ["llm_classify", "text"]},
            outputs={"route": "string", "reason": "string"},
            x=720,
            y=300,
            title="解析分类结果",
        ),
        if_else(
            "if_route",
            cases=[("premium", "and", [condition(["code_parse", "route"], "is", "premium")])],
            x=1040,
            y=300,
            title="是否高优先级",
        ),
        llm(
            "llm_premium",
            model=openai("gpt-4o", temperature=0.3, max_tokens=1200),
            system="You are a senior account manager. Draft a same-day response with an owner and a deadline.",
            user="Request:\n{{#start.request#}}\n\nRouting reason: {{#code_parse.reason#}}",
            x=1360,
            y=200,
            title="LLM 高优先级回复",
        ),
        llm(
            "llm_standard",
            model=openai("gpt-4o-mini", temperature=0.5, max_tokens=800),
            system="You are a support agent. Draft a helpful first response and list any missing information.",
            user="Request:\n{{#start.request#}}",
            x=1360,
            y=440,
            title="LLM 常规回复",
        ),
        variable_aggregator(
            "agg_reply",
            variables=[["llm_premium", "text"], ["llm_standard", "text"]],
            output_type="string",
            x=1700,
            y=300,
            title="合并回复",
        ),
        end("end", [out("reply", "agg_reply", "output")], x=2020, y=300),
    ]
    edges = [
        edge("start", "llm_classify", "start", "llm"),
        edge("llm_classify", "code_parse", "llm", "code"),
        edge("code_parse", "if_route", "code", "if-else"),
        edge("if_route", "llm_premium", "if-else", "llm", source_handle="premium", edge_id="edge-route-premium"),
        edge("if_route", "llm_standard", "if-else", "llm", source_handle="false", edge_id="edge-route-standard"),
        edge("llm_premium", "agg_reply", "llm", "variable-aggregator", edge_id="edge-premium-agg"),
        edge("llm_standard", "agg_reply", "llm", "variable-aggregator", edge_id="edge-standard-agg"),
        edge("agg_reply", "end", "variable-aggregator", "end"),
    ]
    return app_dsl(
        "Branching Workflow",
        "workflow",
        nodes=nodes,
        edges=edges,
        description="Classify a request with an LLM, branch on the result, and merge both branches back together.",
        icon="🔀",
        icon_background="#E0F2FE",
    )


# ==========================================================================
# 4. agent-with-tools — tool-calling agent driven by a plugin strategy
# ==========================================================================


def build_agent_with_tools() -> dict[str, Any]:
    nodes = [
        start("start", [], x=80, y=300),
        agent(
            "agent_research",
            strategy_name="ReAct",
            parameters={
                "model": {"type": "constant", "value": openai("gpt-4o", temperature=0.2)},
                "tools": {"type": "constant", "value": []},
                "instruction": {
                    "type": "mixed",
                    "value": (
                        "Answer the user's question using the available tools.\n"
                        "- Plan before acting; use one tool at a time.\n"
                        "- Cite every fact you took from a tool result.\n"
                        "- If no tool can answer it, say so instead of guessing."
                    ),
                },
                "query": {"type": "mixed", "value": ""},
                "maximum_iterations": {"type": "constant", "value": 10},
            },
            x=400,
            y=300,
            title="Agent 研究",
        ),
        end("end", [out("answer", "agent_research", "text")], x=760, y=300),
    ]
    edges = [
        edge("start", "agent_research", "start", "agent"),
        edge("agent_research", "end", "agent", "end"),
    ]
    return app_dsl(
        "Agent with Tools",
        "workflow",
        nodes=nodes,
        edges=edges,
        description=(
            "Tool-calling agent. The agent node is driven by a plugin strategy, so its tools and "
            "credentials are configured in the workspace, not in this file."
        ),
        icon="🤖",
        icon_background="#FEF3C7",
    )


# ==========================================================================
# 5. notification-multi — severity routing to SMS / IM / email
# ==========================================================================


def build_notification_multi() -> dict[str, Any]:
    nodes = [
        start("start", [paragraph("alert", "Alert payload (free text or JSON)")], x=80, y=340),
        parameter_extractor(
            "extract_alert",
            model=openai("gpt-4o-mini", temperature=0.0, max_tokens=512),
            query_selector=["start", "alert"],
            parameters=[
                extract_param("severity", description="One of: severe, medium, minor", param_type="select",
                              options=["severe", "medium", "minor"]),
                extract_param("summary", description="One-sentence summary, under 40 words", param_type="string"),
                extract_param("service", description="Affected service name", param_type="string", required=False),
            ],
            instruction=(
                "Extract the incident fields from the alert. Read severity carefully: "
                "severe = outage or data loss, medium = degraded service, minor = informational."
            ),
            x=400,
            y=340,
            title="提取告警要素",
        ),
        if_else(
            "if_severity",
            cases=[
                ("severe", "and", [condition(["extract_alert", "severity"], "is", "severe")]),
                ("medium", "and", [condition(["extract_alert", "severity"], "is", "medium")]),
            ],
            x=720,
            y=340,
            title="告警等级",
        ),
        http_request(
            "http_sms",
            url="{{env.SMS_WEBHOOK_URL}}",
            method="post",
            body=json_body([
                {"key": "text", "value": "[SEVERE] {{#extract_alert.summary#}} ({{#extract_alert.service#}})",
                 "type": "text"},
            ]),
            x=1060,
            y=120,
            title="短信通知",
        ),
        http_request(
            "http_im",
            url="{{env.DINGTALK_WEBHOOK}}",
            method="post",
            headers="Content-Type: application/json",
            body=json_body([
                {"key": "msgtype", "value": "text", "type": "text"},
                {"key": "text", "value": '{"content": "[SEVERE] {{#extract_alert.summary#}}"}', "type": "text"},
            ]),
            x=1060,
            y=280,
            title="钉钉通知",
        ),
        http_request(
            "http_email",
            url="{{env.EMAIL_API_URL}}",
            method="post",
            headers="Authorization: Bearer {{env.EMAIL_API_KEY}}\nContent-Type: application/json",
            body=json_body([
                {"key": "to", "value": "{{env.ONCALL_EMAIL}}", "type": "text"},
                {"key": "subject", "value": "[MEDIUM] {{#extract_alert.service#}}", "type": "text"},
                {"key": "body", "value": "{{#extract_alert.summary#}}", "type": "text"},
            ]),
            x=1060,
            y=440,
            title="邮件通知",
        ),
        http_request(
            "http_im_minor",
            url="{{env.FEISHU_WEBHOOK}}",
            method="post",
            headers="Content-Type: application/json",
            body=json_body([
                {"key": "msg_type", "value": "text", "type": "text"},
                {"key": "content", "value": '{"text": "[MINOR] {{#extract_alert.summary#}}"}', "type": "text"},
            ]),
            x=1060,
            y=600,
            title="飞书通知",
        ),
        variable_aggregator(
            "agg_result",
            variables=[["http_sms", "body"], ["http_im", "body"], ["http_email", "body"], ["http_im_minor", "body"]],
            output_type="string",
            x=1420,
            y=340,
            title="合并通知结果",
        ),
        end(
            "end",
            [
                out("notify_result", "agg_result", "output"),
                out("severity", "extract_alert", "severity"),
                out("summary", "extract_alert", "summary"),
            ],
            x=1740,
            y=340,
        ),
    ]
    edges = [
        edge("start", "extract_alert", "start", "parameter-extractor"),
        edge("extract_alert", "if_severity", "parameter-extractor", "if-else"),
        edge("if_severity", "http_sms", "if-else", "http-request", source_handle="severe", edge_id="edge-sev-sms"),
        edge("if_severity", "http_im", "if-else", "http-request", source_handle="severe", edge_id="edge-sev-im"),
        edge("if_severity", "http_email", "if-else", "http-request", source_handle="medium", edge_id="edge-med-mail"),
        edge("if_severity", "http_im_minor", "if-else", "http-request", source_handle="false", edge_id="edge-minor-im"),
        edge("http_sms", "agg_result", "http-request", "variable-aggregator", edge_id="edge-sms-agg"),
        edge("http_im", "agg_result", "http-request", "variable-aggregator", edge_id="edge-im-agg"),
        edge("http_email", "agg_result", "http-request", "variable-aggregator", edge_id="edge-mail-agg"),
        edge("http_im_minor", "agg_result", "http-request", "variable-aggregator", edge_id="edge-minor-agg"),
        edge("agg_result", "end", "variable-aggregator", "end"),
    ]
    return app_dsl(
        "Multi-channel Notification",
        "workflow",
        nodes=nodes,
        edges=edges,
        description="Extract incident severity, then fan out to SMS + DingTalk (severe), email (medium), or Feishu (minor).",
        icon="🚨",
        icon_background="#FEE2E2",
        environment_variables=[
            env_var("SMS_WEBHOOK_URL", "https://sms.example.com/send", description="SMS gateway endpoint"),
            env_var("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=", description="DingTalk bot"),
            env_var("FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/", description="Feishu bot"),
            env_var("EMAIL_API_URL", "https://api.example.com/v3/mail/send", description="Transactional email API"),
            env_var("EMAIL_API_KEY", "", "secret", description="Email API token"),
            env_var("ONCALL_EMAIL", "oncall@example.com", description="On-call mailing list"),
        ],
    )


# ==========================================================================
# 6. multi-agent-router — intent classification into specialist agents
# ==========================================================================


def build_multi_agent_router() -> dict[str, Any]:
    spec = (
        ("general", "agent_general", "Handle anything that is not clearly sales, billing, or technical."),
        ("sales", "agent_sales", "Pricing, plans, quotes, trials, procurement questions."),
        ("billing", "agent_billing", "Invoices, refunds, payment failures, subscription changes."),
        ("technical", "agent_tech", "Bugs, errors, integrations, API usage, how-to questions."),
    )
    nodes: list[dict[str, Any]] = [
        start("start", [], x=80, y=380),
        question_classifier(
            "classifier",
            model=openai("gpt-4o-mini", temperature=0.0, max_tokens=64),
            classes=[(class_id, class_id.capitalize()) for class_id, _, _ in spec],
            instruction=(
                "Route the user's message to the single best team.\n"
                "sales = pricing, plans, quotes, trials.\n"
                "billing = invoices, refunds, payment failures.\n"
                "technical = bugs, errors, API, integrations.\n"
                "general = anything else."
            ),
            x=400,
            y=380,
            title="意图分类",
        ),
    ]
    agent_nodes = []
    for index, (_, node_id, brief) in enumerate(spec):
        agent_nodes.append(
            agent(
                node_id,
                strategy_name="FunctionCalling",
                strategy_label="FunctionCalling",
                parameters={
                    "model": {"type": "constant", "value": openai("gpt-4o", temperature=0.3)},
                    "tools": {"type": "constant", "value": []},
                    "instruction": {"type": "mixed", "value": brief},
                    "query": {"type": "mixed", "value": ""},
                    "maximum_iterations": {"type": "constant", "value": 6},
                },
                x=760,
                y=120 + index * 170,
                title=f"Agent {node_id}",
            )
        )
    nodes.extend(agent_nodes)
    nodes.append(
        variable_aggregator(
            "agg_reply",
            variables=[[node_id, "text"] for _, node_id, _ in spec],
            output_type="string",
            x=1100,
            y=380,
            title="合并回复",
        )
    )
    nodes.append(answer("answer", "{{#agg_reply.output#}}", x=1420, y=380))

    edges = [edge("start", "classifier", "start", "question-classifier")]
    for class_id, node_id, _ in spec:
        edges.append(
            edge(
                "classifier",
                node_id,
                "question-classifier",
                "agent",
                source_handle=class_id,
                edge_id=f"edge-cls-{class_id}",
            )
        )
        edges.append(edge(node_id, "agg_reply", "agent", "variable-aggregator", edge_id=f"edge-{node_id}-agg"))
    edges.append(edge("agg_reply", "answer", "variable-aggregator", "answer"))

    return app_dsl(
        "Multi-Agent Router",
        "advanced-chat",
        nodes=nodes,
        edges=edges,
        description="Classify intent, then hand the conversation to a specialist agent and merge the replies.",
        icon="🧭",
        icon_background="#EDE9FE",
        features=default_features(
            chat=True,
            opening_statement="Hi! Ask about pricing, billing, or a technical issue and I'll route you to the right team.",
        ),
    )


# ==========================================================================
# 7. data-analysis — NL question to guarded SQL to emailed report
# ==========================================================================

SQL_GUARD_CODE = '''import re


FORBIDDEN = re.compile(
    r"\\b(insert|update|delete|drop|alter|truncate|grant|revoke|create|attach|copy)\\b",
    re.IGNORECASE,
)
TABLES = {"orders", "order_items", "customers", "products"}


def main(llm_output: str) -> dict:
    """Keep only the first SELECT statement and refuse anything that writes.

    This node is a guard, not a sandbox: the SQL gateway behind the HTTP node must
    still run under a read-only role with a statement timeout.
    """
    sql = (llm_output or "").strip()
    fence = re.search(r"```(?:sql)?\\s*(.*?)```", sql, re.DOTALL)
    if fence:
        sql = fence.group(1).strip()
    sql = sql.rstrip(";").strip()

    if not sql:
        return {"sql": "", "ok": "false", "error": "empty SQL"}

    lowered = sql.lower()
    if not lowered.startswith(("select", "with")):
        return {"sql": "", "ok": "false", "error": "only SELECT is allowed"}
    if FORBIDDEN.search(sql):
        return {"sql": "", "ok": "false", "error": "statement contains a write keyword"}

    mentioned = set(re.findall(r"\\bfrom\\s+([a-z_][a-z0-9_]*)", lowered))
    mentioned |= set(re.findall(r"\\bjoin\\s+([a-z_][a-z0-9_]*)", lowered))
    unknown = {t for t in mentioned if t not in TABLES}
    if unknown:
        return {"sql": "", "ok": "false", "error": "unknown table: " + ", ".join(sorted(unknown))}

    if " limit " not in lowered:
        sql = sql + " LIMIT 500"
    return {"sql": sql, "ok": "true", "error": ""}
'''

FORMAT_ROWS_CODE = '''import json


def main(body: str) -> dict:
    """Shape the gateway response into a compact CSV-ish digest for the LLM."""
    try:
        payload = json.loads(body or "{}")
    except Exception:
        return {"rows_csv": "", "row_count": "0", "parse_error": "true"}

    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {"rows_csv": "", "row_count": "0", "parse_error": "true"}

    if not rows:
        return {"rows_csv": "(no rows)", "row_count": "0", "parse_error": "false"}

    header = list(rows[0].keys()) if isinstance(rows[0], dict) else []
    lines = [",".join(header)]
    for row in rows[:200]:
        lines.append(",".join(str(row.get(col, "")) for col in header))
    return {"rows_csv": "\\n".join(lines), "row_count": str(len(rows)), "parse_error": "false"}
'''


def build_data_analysis() -> dict[str, Any]:
    nodes = [
        start(
            "start",
            [paragraph("question", "Analytics question")],
            x=80,
            y=340,
        ),
        llm(
            "llm_sql",
            model=openai("gpt-4o", temperature=0.0, max_tokens=512, json_object=True),
            system=(
                "Write one read-only PostgreSQL SELECT for the analytics question.\n"
                "Schema:\n"
                "  orders(id, customer_id, status, total_amount, currency, created_at)\n"
                "  order_items(order_id, product_id, quantity, unit_price)\n"
                "  customers(id, name, region, segment)\n"
                "  products(id, sku, name, category)\n"
                "Rules:\n"
                "- SELECT or WITH only, never a write.\n"
                "- Always bound the row count.\n"
                "- Output SQL only, no commentary, no markdown fences."
            ),
            user="{{#start.question#}}",
            x=400,
            y=340,
            title="LLM 生成 SQL",
        ),
        code(
            "code_guard",
            code_text=SQL_GUARD_CODE,
            variables={"llm_output": ["llm_sql", "text"]},
            outputs={"sql": "string", "ok": "string", "error": "string"},
            x=720,
            y=340,
            title="SQL 守卫",
        ),
        if_else(
            "if_safe",
            cases=[("safe", "and", [condition(["code_guard", "ok"], "is", "true")])],
            x=1040,
            y=340,
            title="SQL 是否安全",
        ),
        http_request(
            "http_query",
            url="{{env.SQL_GATEWAY_URL}}",
            method="post",
            headers="Authorization: Bearer {{env.SQL_GATEWAY_TOKEN}}\nContent-Type: application/json",
            body=json_body([{"key": "sql", "value": "{{#code_guard.sql#}}", "type": "text"}]),
            timeout={"connect": 10, "read": 60, "write": 10},
            x=1360,
            y=240,
            title="执行查询",
        ),
        code(
            "code_format",
            code_text=FORMAT_ROWS_CODE,
            variables={"body": ["http_query", "body"]},
            outputs={"rows_csv": "string", "row_count": "string", "parse_error": "string"},
            x=1700,
            y=240,
            title="格式化结果",
        ),
        llm(
            "llm_analyze",
            model=openai("gpt-4o", temperature=0.2, max_tokens=2000),
            system=(
                "Analyse the query result for the business question.\n"
                "Rules:\n"
                "- Lead with the direct answer in one sentence.\n"
                "- Then at most 4 bullet observations, each with the number that supports it.\n"
                "- State the row count you were given; if it is 0 or the parse flag is true, say the "
                "data could not be read instead of speculating."
            ),
            user=(
                "Question: {{#start.question#}}\n\n"
                "SQL:\n{{#code_guard.sql#}}\n\n"
                "Rows ({{#code_format.row_count#}} total, parse_error={{#code_format.parse_error#}}):\n"
                "{{#code_format.rows_csv#}}"
            ),
            x=2040,
            y=240,
            title="LLM 分析",
        ),
        template_transform(
            "build_report",
            template=(
                "Analysis question: {{ question }}\n\n"
                "{{ analysis }}\n\n"
                "---\nSQL:\n{{ sql }}\n"
                "Rows returned: {{ row_count }}\n"
                "Generated by Dify data-analysis workflow."
            ),
            variables={
                "question": ["start", "question"],
                "analysis": ["llm_analyze", "text"],
                "sql": ["code_guard", "sql"],
                "row_count": ["code_format", "row_count"],
            },
            x=2380,
            y=240,
            title="组装报告",
        ),
        http_request(
            "http_send",
            url="{{env.EMAIL_API_URL}}",
            method="post",
            headers="Authorization: Bearer {{env.EMAIL_API_KEY}}\nContent-Type: application/json",
            body=json_body([
                {"key": "to", "value": "{{env.REPORT_RECIPIENT}}", "type": "text"},
                {"key": "subject", "value": "Analytics report", "type": "text"},
                {"key": "body", "value": "{{#build_report.output#}}", "type": "text"},
            ]),
            x=2720,
            y=280,
            title="邮件发送报告",
        ),
        llm(
            "llm_refuse",
            model=openai("gpt-4o-mini", temperature=0.0, max_tokens=300),
            system=(
                "The generated SQL was rejected by the guard. Explain the problem in plain language "
                "and ask one clarifying question. Never show raw SQL."
            ),
            user="Rejection reason: {{#code_guard.error#}}\n\nOriginal question: {{#start.question#}}",
            x=1360,
            y=560,
            title="LLM 拒绝说明",
        ),
        variable_aggregator(
            "agg_report",
            variables=[["build_report", "output"], ["llm_refuse", "text"]],
            output_type="string",
            x=3060,
            y=380,
            title="合并输出",
        ),
        end(
            "end",
            [
                out("report", "agg_report", "output"),
                out("sql", "code_guard", "sql"),
                out("guard_error", "code_guard", "error"),
                out("row_count", "code_format", "row_count"),
            ],
            x=3380,
            y=380,
        ),
    ]
    edges = [
        edge("start", "llm_sql", "start", "llm"),
        edge("llm_sql", "code_guard", "llm", "code"),
        edge("code_guard", "if_safe", "code", "if-else"),
        edge("if_safe", "http_query", "if-else", "http-request", source_handle="safe", edge_id="edge-safe-query"),
        edge("if_safe", "llm_refuse", "if-else", "llm", source_handle="false", edge_id="edge-unsafe-refuse"),
        edge("http_query", "code_format", "http-request", "code"),
        edge("code_format", "llm_analyze", "code", "llm"),
        edge("llm_analyze", "build_report", "llm", "template-transform"),
        edge("build_report", "http_send", "template-transform", "http-request"),
        edge("build_report", "agg_report", "template-transform", "variable-aggregator", edge_id="edge-report-agg"),
        edge("llm_refuse", "agg_report", "llm", "variable-aggregator", edge_id="edge-refuse-agg"),
        edge("agg_report", "end", "variable-aggregator", "end"),
    ]
    return app_dsl(
        "SQL Data Analysis",
        "workflow",
        nodes=nodes,
        edges=edges,
        description=(
            "Turn a natural-language analytics question into guarded read-only SQL, "
            "analyse the rows, and email a report."
        ),
        icon="📊",
        icon_background="#DBEAFE",
        environment_variables=[
            env_var("SQL_GATEWAY_URL", "https://data.example.com/query", description="Read-only SQL gateway"),
            env_var("SQL_GATEWAY_TOKEN", "", "secret", description="Gateway bearer token"),
            env_var("EMAIL_API_URL", "https://api.example.com/v3/mail/send", description="Email API endpoint"),
            env_var("EMAIL_API_KEY", "", "secret", description="Email API token"),
            env_var("REPORT_RECIPIENT", "analytics@example.com", description="Report recipient"),
        ],
    )


# ==========================================================================
# 8. content-generator — parallel drafting then a single editing pass
# ==========================================================================


def build_content_generator() -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        start(
            "start",
            [
                text_input("topic", "Topic"),
                text_input("audience", "Audience", required=False),
                select_input("tone", "Tone", ["practical", "conversational", "authoritative"]),
                number_input("word_limit", "Word limit", required=False),
            ],
            x=80,
            y=380,
        ),
        llm(
            "llm_outline",
            model=openai("gpt-4o", temperature=0.6, max_tokens=900),
            system=(
                "You are an outline editor. Produce a numbered outline of 5 to 7 sections.\n"
                "Each line: '<n>. <section title> — <one clause on what it covers>'.\n"
                "Output the outline only."
            ),
            user="Topic: {{#start.topic#}}\nAudience: {{#start.audience#}}\nTone: {{#start.tone#}}",
            x=420,
            y=160,
            title="LLM 大纲",
        ),
        llm(
            "llm_facts",
            model=openai("gpt-4o", temperature=0.2, max_tokens=900),
            system=(
                "You are a researcher. List 5 to 8 checkable facts or figures relevant to the topic.\n"
                "Mark anything you cannot verify as 'UNVERIFIED' — the editor will decide.\n"
                "Output a plain bullet list only."
            ),
            user="Topic: {{#start.topic#}}\nAudience: {{#start.audience#}}",
            x=420,
            y=380,
            title="LLM 事实要点",
        ),
        llm(
            "llm_angle",
            model=openai("gpt-4o", temperature=0.8, max_tokens=500),
            system=(
                "You are a magazine editor. Propose one sharp angle or hook for this topic, "
                "plus a three-sentence opening paragraph in the requested tone. Output prose only."
            ),
            user="Topic: {{#start.topic#}}\nAudience: {{#start.audience#}}\nTone: {{#start.tone#}}",
            x=420,
            y=600,
            title="LLM 切入点",
        ),
        template_transform(
            "assemble_brief",
            template=(
                "TOPIC: {{ topic }}\nAUDIENCE: {{ audience }}\nTONE: {{ tone }}\n"
                "WORD LIMIT: {{ limit }}\n\n"
                "=== OUTLINE ===\n{{ outline }}\n\n"
                "=== FACTS ===\n{{ facts }}\n\n"
                "=== ANGLE AND OPENING ===\n{{ angle }}"
            ),
            variables={
                "topic": ["start", "topic"],
                "audience": ["start", "audience"],
                "tone": ["start", "tone"],
                "limit": ["start", "word_limit"],
                "outline": ["llm_outline", "text"],
                "facts": ["llm_facts", "text"],
                "angle": ["llm_angle", "text"],
            },
            x=780,
            y=380,
            title="汇总写作简报",
        ),
        llm(
            "llm_write",
            model=openai("gpt-4o", temperature=0.7, max_tokens=3000),
            system=(
                "Write the final article from the brief.\n"
                "Rules:\n"
                "- Follow the outline order; keep every section to one or two paragraphs.\n"
                "- Use the supplied facts only. Drop or flag anything marked UNVERIFIED rather than "
                "presenting it as settled.\n"
                "- Match the requested tone and stay within the word limit.\n"
                "- Output the article only: no preamble, no meta-commentary."
            ),
            user="{{#assemble_brief.output#}}",
            x=1140,
            y=380,
            title="LLM 成稿",
        ),
        llm(
            "llm_edit",
            model=openai("gpt-4o", temperature=0.3, max_tokens=3000),
            system=(
                "You are a copy editor. Tighten the draft: cut filler, split long sentences, "
                "fix repetition. Keep the structure and every fact unchanged. "
                "Output the edited article only."
            ),
            user="Tone: {{#start.tone#}}\nWord limit: {{#start.word_limit#}}\n\nDraft:\n{{#llm_write.text#}}",
            x=1500,
            y=380,
            title="LLM 修订",
        ),
        end(
            "end",
            [
                out("article", "llm_edit", "text"),
                out("outline", "llm_outline", "text"),
            ],
            x=1860,
            y=380,
        ),
    ]
    edges = [
        edge("start", "llm_outline", "start", "llm", edge_id="edge-topic-outline"),
        edge("start", "llm_facts", "start", "llm", edge_id="edge-topic-facts"),
        edge("start", "llm_angle", "start", "llm", edge_id="edge-topic-angle"),
        edge("llm_outline", "assemble_brief", "llm", "template-transform", edge_id="edge-outline-brief"),
        edge("llm_facts", "assemble_brief", "llm", "template-transform", edge_id="edge-facts-brief"),
        edge("llm_angle", "assemble_brief", "llm", "template-transform", edge_id="edge-angle-brief"),
        edge("assemble_brief", "llm_write", "template-transform", "llm"),
        edge("llm_write", "llm_edit", "llm", "llm"),
        edge("llm_edit", "end", "llm", "end"),
    ]
    return app_dsl(
        "Content Generator",
        "workflow",
        nodes=nodes,
        edges=edges,
        description="Draft outline, facts and angle in parallel, assemble a brief, then write and edit the article.",
        icon="✍️",
        icon_background="#FCE7F3",
    )


# ==========================================================================
# 9. iteration-loop — process every item in a list
# ==========================================================================

SPLIT_LIST_CODE = '''import json
import re


def main(raw: str) -> dict:
    """Split pasted input into a clean list of items, one per line or JSON array."""
    text = (raw or "").strip()
    items: list[str] = []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [str(item).strip() for item in parsed]
        except Exception:
            items = []
    if not items:
        items = [line.strip() for line in re.split(r"\\r?\\n", text) if line.strip()]
    items = [item for item in items if item][:50]
    return {"items": items, "count": str(len(items))}
'''

JOIN_RESULTS_CODE = '''import json


def main(results, count: str) -> dict:
    """Turn the iteration output into a single readable report."""
    if isinstance(results, str):
        try:
            results = json.loads(results)
        except Exception:
            results = [results]
    if not isinstance(results, list):
        results = [str(results)]

    lines = []
    for index, item in enumerate(results, 1):
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        lines.append("%d. %s" % (index, " ".join(text.split())))
    report = "Processed %s item(s).\\n\\n%s" % (count, "\\n".join(lines))
    return {"report": report}
'''


def build_iteration_loop() -> dict[str, Any]:
    container_id = "iter_items"
    inner_start_id = f"{container_id}start"

    nodes: list[dict[str, Any]] = [
        start("start", [paragraph("raw_items", "Items, one per line (or a JSON array)")], x=80, y=340),
        code(
            "code_split",
            code_text=SPLIT_LIST_CODE,
            variables={"raw": ["start", "raw_items"]},
            outputs={"items": "array[string]", "count": "string"},
            x=400,
            y=340,
            title="拆分条目",
        ),
    ]
    nodes.extend(
        iteration_container(
            container_id,
            iterator_selector=["code_split", "items"],
            output_selector=["llm_item", "text"],
            x=760,
            y=340,
            is_parallel=True,
            parallel_nums=5,
            error_handle_mode="continue-on-error",
            title="逐条处理",
        )
    )
    inner_llm = llm(
        "llm_item",
        model=openai("gpt-4o-mini", temperature=0.2, max_tokens=600),
        system=(
            "Summarise one item in a single sentence of at most 25 words, then list at most two "
            "action points. Output plain text."
        ),
        user="Item:\n{{#iter_items.item#}}",
        x=1000,
        y=440,
        title="LLM 单条处理",
    )
    nodes.extend(
        [
            in_container(inner_llm, container_id, "iteration"),
            code(
                "code_join",
                code_text=JOIN_RESULTS_CODE,
                variables={"results": [container_id, "output"], "count": ["code_split", "count"]},
                outputs={"report": "string"},
                x=1620,
                y=340,
                title="汇总结果",
            ),
            end(
                "end",
                [
                    out("report", "code_join", "report"),
                    out("item_count", "code_split", "count"),
                ],
                x=1940,
                y=340,
            ),
        ]
    )

    edges = [
        edge("start", "code_split", "start", "code"),
        edge("code_split", container_id, "code", "iteration"),
        inner_edge(inner_start_id, "llm_item", "iteration-start", "llm"),
        edge(container_id, "code_join", "iteration", "code"),
        edge("code_join", "end", "code", "end"),
    ]
    return app_dsl(
        "Iteration Batch Processor",
        "workflow",
        nodes=nodes,
        edges=edges,
        description="Split pasted input into items, summarise each inside an iteration container, then join the results.",
        icon="🔁",
        icon_background="#CFFAFE",
    )


# ==========================================================================
# Examples
# ==========================================================================


def build_example_doc_qa() -> dict[str, Any]:
    return app_dsl(
        "Doc Q&A System",
        "advanced-chat",
        nodes=[
            start("start", [file_input("upload", "Optional document", extensions=[".pdf", ".docx", ".md"], required=False)],
                  x=80, y=340),
            document_extractor("extract_doc", variable_selector=["start", "upload"], x=400, y=220, title="解析上传文档"),
            knowledge_retrieval(
                "retriever",
                query_selector=["sys", "query"],
                top_k=4,
                reranking_enable=True,
                x=400,
                y=440,
                title="知识检索",
            ),
            llm(
                "llm_answer",
                model=openai("gpt-4o", temperature=0.2, max_tokens=1600),
                system=(
                    "Answer from the retrieved context and, when a document was uploaded, from that "
                    "document as well.\n"
                    "Rules:\n"
                    "- Cite each claim as [Source N] (knowledge base) or [Uploaded doc] (attachment).\n"
                    "- If neither source covers the question, say so and offer to escalate.\n"
                    "- Quote exact clause numbers when you rely on one."
                ),
                user=(
                    "Uploaded document (may be empty):\n{{#extract_doc.text#}}\n\n"
                    "Knowledge base context:\n{{#context#}}\n\n"
                    "Question:\n{{#sys.query#}}"
                ),
                context_selector=["retriever", "result"],
                memory=True,
                memory_window=10,
                x=780,
                y=340,
                title="LLM 回答",
            ),
            answer("answer", "{{#llm_answer.text#}}", x=1140, y=340),
        ],
        edges=[
            edge("start", "extract_doc", "start", "document-extractor"),
            edge("start", "retriever", "start", "knowledge-retrieval"),
            edge("extract_doc", "llm_answer", "document-extractor", "llm"),
            edge("retriever", "llm_answer", "knowledge-retrieval", "llm"),
            edge("llm_answer", "answer", "llm", "answer"),
        ],
        description="Answer questions from a knowledge base, optionally grounding on a document the user uploads.",
        icon="📖",
        icon_background="#E0F2FE",
        features=default_features(
            chat=True,
            opening_statement="Ask about our documents, or upload one of your own.",
            suggested_questions=["What does the contract template require?", "Summarise the uploaded document."],
        ),
        environment_variables=[],
    )


def build_example_auto_notification() -> dict[str, Any]:
    return app_dsl(
        "Auto Notification",
        "workflow",
        nodes=[
            start("start", [paragraph("message", "Message to send")], x=80, y=300),
            parameter_extractor(
                "extract_route",
                model=openai("gpt-4o-mini", temperature=0.0, max_tokens=256),
                query_selector=["start", "message"],
                parameters=[
                    extract_param("channel", description="Delivery channel", param_type="select",
                                  options=["slack", "email"]),
                    extract_param("subject", description="Short subject line", param_type="string"),
                ],
                instruction="Decide whether this message is routine (slack) or needs a paper trail (email).",
                x=400,
                y=300,
                title="判断渠道",
            ),
            if_else(
                "if_channel",
                cases=[("email", "and", [condition(["extract_route", "channel"], "is", "email")])],
                x=720,
                y=300,
                title="渠道分支",
            ),
            http_request(
                "http_email",
                url="{{env.EMAIL_API_URL}}",
                method="post",
                headers="Authorization: Bearer {{env.EMAIL_API_KEY}}\nContent-Type: application/json",
                body=json_body([
                    {"key": "to", "value": "{{env.NOTIFY_EMAIL}}", "type": "text"},
                    {"key": "subject", "value": "{{#extract_route.subject#}}", "type": "text"},
                    {"key": "body", "value": "{{#start.message#}}", "type": "text"},
                ]),
                x=1060,
                y=220,
                title="发送邮件",
            ),
            http_request(
                "http_slack",
                url="{{env.SLACK_WEBHOOK}}",
                method="post",
                headers="Content-Type: application/json",
                body=json_body([{"key": "text", "value": "{{#start.message#}}", "type": "text"}]),
                x=1060,
                y=440,
                title="发送 Slack",
            ),
            variable_aggregator(
                "agg_status",
                variables=[["http_email", "status_code"], ["http_slack", "status_code"]],
                output_type="number",
                x=1400,
                y=300,
                title="合并状态",
            ),
            end("end", [out("status", "agg_status", "output", "number")], x=1720, y=300),
        ],
        edges=[
            edge("start", "extract_route", "start", "parameter-extractor"),
            edge("extract_route", "if_channel", "parameter-extractor", "if-else"),
            edge("if_channel", "http_email", "if-else", "http-request", source_handle="email", edge_id="edge-mail"),
            edge("if_channel", "http_slack", "if-else", "http-request", source_handle="false", edge_id="edge-slack"),
            edge("http_email", "agg_status", "http-request", "variable-aggregator", edge_id="edge-mail-agg"),
            edge("http_slack", "agg_status", "http-request", "variable-aggregator", edge_id="edge-slack-agg"),
            edge("agg_status", "end", "variable-aggregator", "end"),
        ],
        description="Route a message to Slack or email based on an LLM's channel decision.",
        icon="🔔",
        icon_background="#FEF9C3",
        environment_variables=[
            env_var("EMAIL_API_URL", "https://api.example.com/v3/mail/send"),
            env_var("EMAIL_API_KEY", "", "secret"),
            env_var("NOTIFY_EMAIL", "ops@example.com"),
            env_var("SLACK_WEBHOOK", "https://hooks.slack.com/services/"),
        ],
    )


def build_example_customer_service() -> dict[str, Any]:
    return app_dsl(
        "Customer Service Bot",
        "advanced-chat",
        nodes=[
            start("start", [], x=80, y=340),
            llm(
                "llm_rewrite",
                model=openai("gpt-4o-mini", temperature=0.0, max_tokens=128),
                system=(
                    "Rewrite the user's latest message as a standalone search query.\n"
                    "- Resolve pronouns using the conversation history.\n"
                    "- Output the query only, no quotes, no explanation.\n"
                    "- If it is already standalone, repeat it unchanged."
                ),
                user="{{#sys.query#}}",
                memory=True,
                x=400,
                y=340,
                title="LLM 问题改写",
            ),
            knowledge_retrieval(
                "retriever",
                query_selector=["llm_rewrite", "text"],
                top_k=4,
                reranking_enable=True,
                x=720,
                y=340,
                title="知识检索",
            ),
            llm(
                "llm_answer",
                model=openai("gpt-4o-mini", temperature=0.3, max_tokens=1200),
                system=(
                    "You are a customer service agent.\n"
                    "Rules:\n"
                    "- Answer from the reference material; cite it as [Source N].\n"
                    "- If the material does not cover it, say you will escalate and ask for the "
                    "detail the team needs.\n"
                    "- Never promise a refund, discount, or timeline you cannot verify."
                ),
                user="Reference:\n{{#context#}}\n\nCustomer question:\n{{#sys.query#}}",
                context_selector=["retriever", "result"],
                memory=True,
                memory_window=10,
                x=1040,
                y=340,
                title="LLM 客服回答",
            ),
            answer("answer", "{{#llm_answer.text#}}", x=1360, y=340),
        ],
        edges=[
            edge("start", "llm_rewrite", "start", "llm"),
            edge("llm_rewrite", "retriever", "llm", "knowledge-retrieval"),
            edge("retriever", "llm_answer", "knowledge-retrieval", "llm"),
            edge("llm_answer", "answer", "llm", "answer"),
        ],
        description="Multi-turn support bot that rewrites follow-ups into search queries before retrieving.",
        icon="🎧",
        icon_background="#DCFCE7",
        features=default_features(chat=True, opening_statement="Hi! How can I help today?"),
    )


def build_root_demo() -> dict[str, Any]:
    """The generic local-RAG demo referenced from the skill's README."""
    return app_dsl(
        "Local RAG Bot",
        "advanced-chat",
        nodes=[
            start("start", [], x=80, y=300),
            knowledge_retrieval(
                "retriever",
                query_selector=["sys", "query"],
                top_k=5,
                reranking_enable=True,
                x=400,
                y=300,
                title="知识检索",
            ),
            llm(
                "llm_answer",
                model=deepseek("deepseek-v4-flash", temperature=0.3, max_tokens=2048),
                system=(
                    "Answer strictly from the retrieved context.\n"
                    "- If the context is insufficient, say the knowledge base has no relevant entry.\n"
                    "- End with a source list naming the document and clause you used."
                ),
                user="Context:\n{{#context#}}\n\nQuestion:\n{{#sys.query#}}",
                context_selector=["retriever", "result"],
                memory=True,
                memory_window=10,
                x=760,
                y=300,
                title="LLM 回答",
            ),
            answer("answer", "{{#llm_answer.text#}}", x=1120, y=300),
        ],
        edges=[
            edge("start", "retriever", "start", "knowledge-retrieval"),
            edge("retriever", "llm_answer", "knowledge-retrieval", "llm"),
            edge("llm_answer", "answer", "llm", "answer"),
        ],
        description="Local RAG assistant: retrieve from a Dify knowledge base, answer with citations.",
        icon="📚",
        icon_background="#E8FFD5",
        features=default_features(
            chat=True,
            opening_statement="Ask me anything about the documents in this knowledge base.",
            suggested_questions=["What is the expense policy?", "How do I submit a contract for review?"],
        ),
        conversation_variables=[conversation_var("user_name", "", "string", "Recalled across turns")],
    )


# ==========================================================================
# Driver
# ==========================================================================

BUILDERS = {
    TEMPLATES_DIR / "chatflow-basic.yml": build_chatflow_basic,
    TEMPLATES_DIR / "rag-qa.yml": build_rag_qa,
    TEMPLATES_DIR / "workflow-branching.yml": build_workflow_branching,
    TEMPLATES_DIR / "agent-with-tools.yml": build_agent_with_tools,
    TEMPLATES_DIR / "notification-multi.yml": build_notification_multi,
    TEMPLATES_DIR / "multi-agent-router.yml": build_multi_agent_router,
    TEMPLATES_DIR / "data-analysis.yml": build_data_analysis,
    TEMPLATES_DIR / "content-generator.yml": build_content_generator,
    TEMPLATES_DIR / "iteration-loop.yml": build_iteration_loop,
    EXAMPLES_DIR / "doc-qa-system" / "dsl.yml": build_example_doc_qa,
    EXAMPLES_DIR / "auto-notification" / "dsl.yml": build_example_auto_notification,
    EXAMPLES_DIR / "customer-service-bot" / "dsl.yml": build_example_customer_service,
    SKILL_DIR / "dify-rag-bot.yml": build_root_demo,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate bundled Dify DSL templates")
    parser.add_argument("--check", action="store_true", help="exit 1 when a file is out of date")
    args = parser.parse_args()

    stale: list[Path] = []
    for path, builder in BUILDERS.items():
        import io

        import yaml

        dsl = builder()
        rendered = yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096)
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(path)
            continue
        dump(dsl, path)
        print(f"wrote {path.relative_to(SKILL_DIR)}")

    if args.check:
        if stale:
            for path in stale:
                print(f"stale: {path.relative_to(SKILL_DIR)}", file=sys.stderr)
            return 1
        print("all templates up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
