# Agents and tools

An **agent node** lets the model choose tools and iterate; a **tool node** calls exactly
one tool with fixed inputs. Both are driven by plugins, so their configuration is
partly workspace-specific.

## Agent node

```yaml
- data:
    type: agent
    title: Agent 研究
    desc: ''
    selected: false
    agent_strategy_provider_name: langgenius/agent/agent
    agent_strategy_name: ReAct            # ReAct | FunctionCalling
    agent_strategy_label: ReAct
    agent_parameters:                     # a MAP keyed by parameter name
      model:
        type: constant
        value: {provider: langgenius/openai/openai, name: gpt-4o, mode: chat,
                completion_params: {temperature: 0.2}}
      tools:
        type: constant
        value: []                         # [{provider_name, tool_name, params, enabled, credential_id}]
      instruction:
        type: mixed
        value: |
          Plan before acting; use one tool at a time.
          Cite every fact you took from a tool result.
      query:
        type: mixed
        value: ''
      maximum_iterations:
        type: constant
        value: 10
    memory:
      query_prompt_template: '{{#sys.query#}}'
      window: {enabled: false, size: 10}
```

The shape detail that matters: **`agent_parameters` is a dict**, not a list of
`{name, type, value}` objects. The list form appears in older tutorials and is what the
frontend sends over the wire in some paths, but the node model here takes a map.

Each parameter's `type` is `constant` (fixed value) or `mixed` (text that may contain
`{{#node.key#}}` references, which lets you inject upstream data into the instruction).

| Parameter | Type | Notes |
|---|---|---|
| `model` | constant | A model config, same shape as an `llm` node's `model` |
| `tools` | constant | Array of tool bindings |
| `instruction` | mixed | System prompt |
| `query` | mixed | User input; a leading `""` is the frontend default |
| `maximum_iterations` | constant | Hard cap on tool-calling rounds |

### Strategy choice

| Strategy | Use for | Trade-off |
|---|---|---|
| `FunctionCalling` | Well-defined tools, production routes | Fast and cheap; needs a model with native function calling |
| `ReAct` | Models without good function calling, tasks where visible reasoning helps | More tokens and latency; self-corrects more readily |

The strategy must exist in the installed agent plugin
(`agent_strategy_provider_name` + `agent_strategy_name`). If the plugin is not installed
the node imports but is a dead node — this is not something a DSL check can catch, so
verify in the workspace before shipping an agent app.

## Tool node

| Field | Notes |
|---|---|
| `provider_id` | Provider id, e.g. `langgenius/google/google` |
| `provider_type` | `plugin` · `builtin` · `workflow` · `api` · `app` · `dataset-retrieval` · `mcp` |
| `provider_name` | Provider as registered |
| `tool_name` / `tool_label` | Tool id and label |
| `tool_configurations` | Provider-side settings (`{name: {type, value}}`) |
| `tool_parameters` | Per-call inputs (`{name: {type: variable|constant|mixed, value}}`) |
| `credential_id` | Required when the tool needs a credential; must exist in the workspace |

```yaml
- data:
    type: tool
    title: 发送飞书消息
    desc: ''
    selected: false
    provider_id: langgenius/feishu/feishu
    provider_type: plugin
    provider_name: feishu
    tool_name: send_message
    tool_label: Send Message
    tool_configurations:
      app_type: {type: constant, value: self_built}
    tool_parameters:
      receive_id_type: {type: constant, value: open_id}
      receive_id: {type: variable, value: [start, feishu_open_id]}
      content: {type: mixed, value: '{"text": "{{#start.message#}}"}'}
    credential_id: <workspace credential uuid>
```

> A tool node generated without access to the target workspace should be treated as a
> **scaffold**: `credential_id` and the exact parameter names come from the installed
> plugin version. Re-select the tool in the UI after import.

## Tool bindings inside an agent

```yaml
tools:
  type: constant
  value:
    - provider_name: langgenius/tavily/tavily
      tool_name: tavily_search
      params: {}
      enabled: true
      credential_id: <workspace credential uuid>
```

`enabled: false` keeps a tool configured but unavailable to the agent — useful for
staging a tool off without deleting its settings.

## Choosing between agent and tool node

| Need | Use |
|---|---|
| Call one known function with known inputs | `tool` node |
| Let the model decide which tool and how many times | `agent` node |
| Call a plugin-less HTTP API | `http-request` node |
| Call another Dify workflow/app | `tool` node with `provider_type: workflow` / `app` |

Prefer the deterministic option. An agent is worth its cost only when the sequence of
calls genuinely cannot be predetermined; for routing, `question-classifier` plus one
`llm` node per route is cheaper, faster, and testable.

## Guardrails for agent nodes

- **Cap the loop.** `maximum_iterations` is the only thing standing between a confused
  agent and an unbounded bill. 5–10 is typical.
- **Ground the instruction.** Tell the agent to cite tool results and to say when no
  tool can answer. Ungrounded agent output is hard to audit.
- **Constrain the toolset.** More tools means more chances to pick wrong. Give each
  agent the two or three tools its job needs.
- **Model capability matters.** Function-calling quality varies; a weak model plus
  function calling produces malformed calls that the strategy will retry until the
  iteration cap.

## Common tool providers

Names vary by plugin version — verify in the workspace (Tools → search) rather than
trusting this table. `provider_name` is the plugin's provider key, not the display name.

| Capability | Typical `provider_id` | Typical `tool_name` |
|---|---|---|
| Web search | `langgenius/tavily/tavily` | `tavily_search` |
| Web search | `langgenius/google/google` | `google_search` |
| Web search | `langgenius/bing/bing` | `bing_web_search` |
| Web search | `langgenius/brave/brave` | `brave_search` |
| Webpage scraping | `langgenius/firecrawl/firecrawl` | `scrape` / `crawl` |
| Feishu / Lark | `langgenius/feishu/feishu` | `send_message`, `create_doc`, … |
| DingTalk | `langgenius/dingtalk/dingtalk` | `send_message` |
| Slack | `langgenius/slack/slack` | `post_message` |
| Math / utilities | `langgenius/wolframalpha/wolframalpha` | `query` |
| Wikipedia | `langgenius/wikipedia/wikipedia` | `search` |

## Inspecting what an agent did

An agent's outputs are strategy-defined, so if you need an audit trail, extract it
explicitly with a `code` node rather than guessing at output keys:

```yaml
- data:
    type: code
    title: 提取工具调用
    desc: ''
    selected: false
    code_language: python3
    code: |
      import json


      def main(agent_output: str) -> dict:
          try:
              payload = json.loads(agent_output or "{}")
          except Exception:
              payload = {}
          steps = []
          for message in payload.get("messages", []) if isinstance(payload, dict) else []:
              if message.get("role") == "tool":
                  steps.append({
                      "tool": message.get("name", ""),
                      "arguments": str(message.get("tool_call", {}).get("arguments", ""))[:200],
                      "result": str(message.get("content", ""))[:200],
                  })
          return {"steps": steps, "step_count": str(len(steps))}
    variables:
      - variable: agent_output
        value_selector: [agent_research, text]
    outputs:
      steps:
        children: null
        type: array[object]
      step_count:
        children: null
        type: string
```

## Agent apps (mode `agent-chat`)

Dify 1.17 also supports an **agent app** (`app.mode: agent-chat`) whose graph is a single
agent node in the newer v2 shape (`core.workflow.nodes.agent_v2`, discriminated by
`is_dify_agent_node_data`). Its node data differs from the workflow agent node above.
Author agent apps in the UI; if you must generate one, mirror an exported agent app
rather than extrapolating from these fields.
