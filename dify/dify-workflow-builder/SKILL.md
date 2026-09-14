---
name: dify-workflow-builder
description: Build, generate, validate and deploy Dify 1.17 workflows locally. Use this skill whenever the user mentions Dify, wants to build an agent, chatflow, workflow, RAG pipeline, multi-LLM routing, knowledge base, vector retrieval, SMS/email/Slack/Feishu/DingTalk notifications, function-calling tools, code execution nodes, HTTP integrations, conditional branching, iteration or loop containers, or any combination of these. Also trigger when the user uploads a Dify DSL YAML/JSON, says a DSL will not import or the canvas looks broken, asks to debug a Dify app, or asks to turn natural-language requirements into a Dify app. Produces import-ready Dify 1.17 DSL (YAML) validated against Dify's own pydantic node models, plus a deployment checklist. Use it for any task involving Dify, even without the words "Dify workflow" — "build me a local RAG agent with notification", "make a multi-branch workflow that calls multiple LLMs", "帮我搭个能用本地知识库回答公司文档的机器人" all qualify.
---

# Dify Workflow Builder

Turns natural-language requirements into import-ready **Dify 1.17** DSL, then validates
it against the models Dify itself uses.

## The one thing to know first

Dify 1.17's real DSL format is **not** the format in most tutorials, blog posts, or
older versions of this skill. If you write that format, Dify still accepts the import
because node data models allow extra keys — then the frontend fails to render the nodes,
because the canvas looks up a React renderer by the node's top-level `type` and expects
`custom`.

The two differences that cause the most damage:

```yaml
# WRONG — what tutorials show
- type: llm                    # frontend has no renderer for this
  data:
    model: {...}
    prompt_template: [...]     # no title/desc/selected

# RIGHT — Dify 1.17
- data:
    type: llm                  # the semantic kind lives here
    title: LLM 回答
    desc: ''
    selected: false
    model: {...}
    prompt_template: [...]
  id: llm_answer
  position: {x: 400, y: 300}
  positionAbsolute: {x: 400, y: 300}
  selected: false
  sourcePosition: right
  targetPosition: left
  type: custom                 # ALWAYS custom
  width: 244
  height: 200
```

Read `references/dsl-schema.md` before writing any node by hand, and
`references/pitfalls.md` before declaring the job done. `references/node-types.md` has
the exact required fields and output keys for every node kind.

## Workflow — follow these steps in order

### Step 1 — Capture intent

Identify the app kind (`workflow` / `advanced-chat` chatflow / `completion` /
`agent-chat`), the goal end-to-end, inputs, outputs, and which models, knowledge bases,
tools or external services it needs.

### Step 2 — Ask only for what you cannot infer

Batch 1–4 questions in one `AskUserQuestion`. Worth asking:

1. Which LLM provider/model they have configured (a wrong model name silently misbehaves —
   see `pitfalls.md` §3)
2. Whether it needs a knowledge base, and which documents
3. Which external services (SMS / email / Slack / Feishu / DingTalk / HTTP API / tools)
4. Whether chats are multi-turn (drives the retrieval-rewrite pattern)

Pick sensible defaults for everything else and state the assumptions.

### Step 3 — Start from a template, not a blank page

| Scenario | Template |
|---|---|
| Single-turn Q&A / simple chat | `templates/chatflow-basic.yml` |
| Document Q&A with citations | `templates/rag-qa.yml` |
| Branching / conditional / merge | `templates/workflow-branching.yml` |
| Agent with tools | `templates/agent-with-tools.yml` |
| Multi-channel notification fan-out | `templates/notification-multi.yml` |
| Intent routing to specialist agents | `templates/multi-agent-router.yml` |
| SQL / data analysis and reporting | `templates/data-analysis.yml` |
| Parallel drafting then editing | `templates/content-generator.yml` |
| Batch processing a list | `templates/iteration-loop.yml` |

All nine import as-is into 1.17. Customize with the generator rather than by hand:

```bash
python scripts/generate_dsl.py -t rag-qa -o my-app.yml \
    --app-name "Policy Bot" --llm-model deepseek-flash \
    --dataset-ids <uuid> [<uuid> ...]
```

### Step 4 — Compose new graphs with the builder library

When no template fits, do not hand-write envelopes. `scripts/dify_dsl.py` emits the
correct 1.17 structure — node envelopes, edges with handles, container children, the
`features` block, `name`-keyed environment variables:

```python
from dify_dsl import *

nodes = [
    start("start", [paragraph("contract_text", "合同正文")], x=80, y=300),
    llm("llm_judge", model=deepseek(json_object=True), system="...", user="{{#start.contract_text#}}", x=400, y=300),
    code("code_parse", code_text=CODE, variables={"llm_output": ["llm_judge", "text"]},
         outputs={"is_compliant": "string"}, x=720, y=300),
    end("end", [out("is_compliant", "code_parse", "is_compliant")], x=1040, y=300),
]
dsl = app_dsl("Contract Review", "workflow", nodes=nodes, edges=chain(nodes))
dump(dsl, "contract-review.yml")
```

`scripts/build_templates.py` shows every node constructor in use, including iteration
containers and branch handles.

### Step 5 — Validate

```bash
python scripts/validate_dsl.py app.yml     # envelope + grammar, runs anywhere
bash scripts/validate.sh app.yml           # + Dify's own pydantic models, needs the container
```

`validate.sh` copies the file into the running `dify-api` container and validates each
node's `data` against the model the runtime uses — the strongest check short of
importing. Fix every ERROR; treat warnings as real problems (`--strict` promotes them).

### Step 6 — Show the flow

```bash
python scripts/render_flow.py app.yml              # ASCII tree with branch labels
python scripts/render_flow.py app.yml --mermaid     # Mermaid, containers as subgraphs
```

Show the user so they can confirm the topology before importing. The renderer flags
nodes unreachable from `start` — those never execute.

### Step 7 — Deliver

Always produce all four:

1. **DSL file** — validated, ready to import
2. **Flow diagram** — from `render_flow.py`
3. **Variable map** — every variable, its type, which node produces it, who consumes it
4. **Deployment checklist** — model keys, dataset binding, credentials, secrets
   (`references/deployment.md` §4 has the mandatory post-import list)

## Output format

```markdown
# <App Name> — Dify 1.17

## 1. What it does
<one paragraph>

## 2. Flow
<ASCII or Mermaid from render_flow.py>

## 3. DSL (YAML)
<the validated file>

## 4. Variable map
| Variable | Type | Produced by | Consumed by |
|---|---|---|---|

## 5. Import and configure
1. Import the DSL (Studio → Create from blank → ... → Import DSL File)
2. Bind datasets / re-select tool credentials / re-enter secrets
3. Verify the model names exist in this workspace
4. Test

## 6. Test cases
- Input: <sample>  Expected: <result>
```

## Key rules

- **Node `type` is `custom`; the kind is `data.type`.** Non-negotiable.
- **Top level is `app` + `kind: app` + `version: 0.7.0` + `dependencies`.** `kind` is
  never `app-kind`. A version below `0.7.0` imports with warnings and Dify migrates
  nothing, so the graph must already be correct.
- **Edges need `sourceHandle` / `targetHandle`.** Branch edges use the case id (if-else)
  or class id (question-classifier); the else branch is the literal `"false"`. Only
  if-else has an else — a classifier falls back to its **first** class.
- **Environment and conversation variables are keyed by `name`**, not `variable`.
- **Node outputs are `[node_id, output_key]` selectors in data, `{{#node.id#}}` in text.**
  `{{env.X}}` and `{{conversation.x}}` are bare; `{{#context#}}` is the retrieval context.
- **`variable-aggregator.variables` is a list of `[node, key]` pairs**, and it returns the
  first *non-empty* value where `[]` counts as non-empty — order matters.
- **Code nodes use `code_language`, an `outputs` map of `{children, type}`, and a
  `def main(...) -> dict` entrypoint.** The sandbox has no network.
- **`http-request` requires `headers` and `params`** (strings, `""` when unused), and only
  has `no-auth` / `api-key` authorization — bearer and basic go in headers.
- **Never hardcode credentials.** `{{env.X}}` with `value_type: secret`, or the workspace
  credential store for tools. The validator fails on key-shaped literals.
- **JSON-producing LLM nodes need `max_tokens` headroom and a `parse_error` flag** that
  reaches the `end` node, or a truncated answer silently becomes an empty result.
- **Workflows end with `end`; chatflows reply through `answer`.**

## Resources

- `references/dsl-schema.md` — top level, node/edge envelope, containers, variables, features
- `references/node-types.md` — every node kind with required fields and output keys
- `references/pitfalls.md` — symptom → cause → fix for everything that has actually bitten
- `references/variable-syntax.md` — selectors vs `{{#…#}}`, sys/env/conversation scopes
- `references/llm-providers.md` — model configs, the model-name trap, local runtimes
- `references/knowledge-rag.md` — datasets, retrieval tuning, citation cards
- `references/external-services.md` — HTTP node shape, notification recipes, Dify-to-Dify
- `references/agent-tools.md` — agent strategies, tool nodes and credentials
- `references/deployment.md` — Docker, import, post-import checklist, troubleshooting
- `scripts/dify_dsl.py` — the envelope builder; use it instead of hand-writing YAML
- `scripts/build_templates.py` — regenerates every template and example
- `scripts/generate_dsl.py` — copy a template with overrides
- `scripts/validate_dsl.py` / `scripts/validate.sh` — grammar lint / real model validation
- `scripts/render_flow.py` — ASCII and Mermaid flow diagrams
- `templates/*.yml` (9), `examples/*` (3), `dify-rag-bot.yml` — validated 1.17 apps

## Before you finish

- [ ] `validate.sh` reports PASS for every file you deliver
- [ ] Every model name exists in the target workspace (not just in this file)
- [ ] No credentials anywhere in the DSL — only `{{env.X}}` references
- [ ] JSON-producing nodes have `max_tokens` headroom and surface a parse-error flag
- [ ] The deployment notes cover dataset binding, credentials, secrets and triggers,
      because none of them survive an export
- [ ] The flow diagram matches what the user asked for, node by node
