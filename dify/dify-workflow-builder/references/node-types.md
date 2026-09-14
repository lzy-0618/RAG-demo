# Dify 1.17 node reference

Every node kind `langgenius/dify-api:1.17.0` can run, with the `data` fields its
pydantic model actually requires. Field lists come from
`graphon.nodes.*.entities` / `core.workflow.nodes.*.entities`; output keys come from
the node implementations, so they are what you can reference downstream.

Conventions in this file: **bold** = required by the model. All nodes also carry the
envelope from `dsl-schema.md` §2 (`id`, top-level `type: custom`, `data.type`,
`data.title`, `data.desc`, `data.selected`, `position`, `positionAbsolute`,
`selected`, `sourcePosition`, `targetPosition`, `width`, `height`).

The full node-kind registry, straight from `graphon.enums.BuiltinNodeTypes`:

```
start  end  answer  llm  knowledge-retrieval  if-else  code  template-transform
question-classifier  http-request  tool  datasource  variable-aggregator
variable-assigner (legacy)  loop  loop-start  loop-end  iteration  iteration-start
parameter-extractor  assigner  document-extractor  list-operator  agent  human-input
trigger-webhook  trigger-schedule  trigger-plugin
```

---

## start — entry point

| Field | Notes |
|---|---|
| **`variables`** | Array of input declarations. `[]` means the app reads only `{{#sys.query#}}` (typical for chatflows). |

Each variable: **`variable`**, **`label`**, **`type`**, `required`, `description`,
`max_length`, `options`, `default`, `hide`, `json_schema`. For `file` / `file-list`
also `allowed_file_types`, `allowed_file_extensions`, `allowed_file_upload_methods`.

`type` ∈ `text-input` · `paragraph` · `select` · `number` · `file` · `file-list` ·
`checkbox` · `json_object` · `external_data_tool`.

```yaml
- data:
    type: start
    title: 开始
    desc: ''
    selected: false
    variables:
      - variable: contract_text
        label: 合同正文
        type: paragraph
        required: true
        max_length: null
        options: []
```

Outputs: the declared variables. Reference them as `{{#start.contract_text#}}`.

## end — workflow terminal

| Field | Notes |
|---|---|
| **`outputs`** | Array of `{variable, value_type, value_selector}`. |

`value_type` ∈ `string` · `number` · `object` · `array[string]` · `array[object]` ·
`array[number]` · `boolean` · `any` · `file`.

```yaml
- data:
    type: end
    title: 结束
    desc: ''
    selected: false
    outputs:
      - variable: result
        value_type: string
        value_selector: [llm_answer, text]
```

> `value_type` is easy to forget. Without it the node model rejects the file.

## answer — chatflow reply

| Field | Notes |
|---|---|
| **`answer`** | The reply template, e.g. `'{{#llm_answer.text#}}'`. |

Also carries `variables: []` in frontend exports. **A chatflow needs an `answer`
node to reply to the user** — an `end` node terminates the run without rendering a
message. Multiple `answer` nodes are allowed (each emits a separate chat bubble).

## llm

| Field | Notes |
|---|---|
| **`model`** | `{provider, name, mode, completion_params}` |
| **`prompt_template`** | List of `{role, text}`. `role` ∈ `system` · `user` · `assistant` · `tool` |
| **`context`** | `{enabled, variable_selector}` — attach retrieval output here |
| `vision` | `{enabled, configs: {variable_selector: []}}` |
| `memory` | `{query_prompt_template, window: {enabled, size}}` |
| `structured_output` | `{enabled: false}` |
| `prompt_config` | `{jinja2_variables: []}` — only when using Jinja2 prompt edition |
| `reasoning_format` | `tagged` (default) · `separated` |
| `retry_config` | `{enabled, exponential_backoff: {enabled, max_interval, multiplier}, max_retries, retry_interval}` |

Provider/model naming: `provider` is the plugin id (`langgenius/openai/openai`,
`langgenius/deepseek/deepseek`, `langgenius/anthropic/anthropic`,
`langgenius/ollama/ollama`, `langgenius/tongyi/tongyi`). `name` must be a model the
plugin declares — see `llm-providers.md`, this is a common source of silent
misbehaviour.

When `context.enabled` is true you reference the injected text inside the prompt as
`{{#context#}}` (no node id — it is a synthetic variable).

Outputs: `text` · `reasoning_content` · `usage` · `finish_reason` ·
`structured_output` · `files`.

## knowledge-retrieval

| Field | Notes |
|---|---|
| **`dataset_ids`** | Dataset UUIDs. `[]` is legal and means "bind in the UI after import" |
| **`retrieval_mode`** | `multiple` (vector/hybrid search) · `single` (single-model call) |
| `query_variable_selector` | `[node_id, key]` — the search query |
| `multiple_retrieval_config` | `{top_k, score_threshold, reranking_enable, reranking_mode, reranking_model, weights}` |
| `single_retrieval_config` | `{model}` — a model config, for `retrieval_mode: single` |
| `metadata_filtering_mode` | `disabled` · `automatic` · `manual` |
| `vision` | `{enabled, configs: {variable_selector: []}}` |

Outputs: `result` — an array of chunk objects (`content`, `title`, `score`, …).
Attach it to an LLM via `context.variable_selector: [retriever, result]`.

## if-else

| Field | Notes |
|---|---|
| `cases` | Array of `{case_id, id, logical_operator, conditions}`. `id` must equal `case_id` |
| `logical_operator` | `and` (default) · `or` — how a case's conditions combine |

Each condition: **`variable_selector`** (`[node, key]`), **`comparison_operator`**,
`value`, `varType` (`string` · `number` · `boolean` · `array[object]` · …).

Operators: `is` `is not` `contains` `not contains` `start with` `end with` `empty`
`not empty` `=` `≠` `>` `<` `≥` `≤` `is null` `is not null` `in` `not in` `all of`
`exists` `not exists`.

The else branch is implicit: out-edges use `sourceHandle` = case id, or the literal
`"false"`.

```yaml
- data:
    type: if-else
    title: 是否合规
    desc: ''
    selected: false
    logical_operator: and
    cases:
      - case_id: 'true'
        id: 'true'
        logical_operator: and
        conditions:
          - id: cond-compliant
            varType: string
            variable_selector: [code_judge, is_compliant]
            comparison_operator: is
            value: 'true'
```

## code

| Field | Notes |
|---|---|
| **`variables`** | List of `{variable, value_selector}` — one per `main()` parameter |
| **`code_language`** | `python3` · `javascript` |
| **`code`** | Source with a `def main(...) -> dict:` entrypoint |
| **`outputs`** | `{name: {children: null, type: <SegmentType>}}` |
| `dependencies` | `[{name, version}]` for third-party wheels (must be allow-listed in the sandbox) |

Field-name traps: it is **`code_language`**, not `language`; outputs are a **map**,
not a list; and `children` must be present (usually `null`).

```yaml
- data:
    type: code
    title: 解析 JSON
    desc: ''
    selected: false
    code_language: python3
    code: |
      import json


      def main(llm_output: str) -> dict:
          try:
              data = json.loads(llm_output or "{}")
          except Exception:
              data = {}
          return {"is_compliant": "true" if data.get("compliant") else "false"}
    variables:
      - variable: llm_output
        value_selector: [llm_judge, text]
    outputs:
      is_compliant:
        children: null
        type: string
```

Outputs: exactly the keys of `outputs` (each a SegmentType). The sandbox blocks
network access and non-allow-listed imports.

## template-transform

| Field | Notes |
|---|---|
| **`template`** | Jinja2 text; variables are bare names, e.g. `{{ name }}` |
| **`variables`** | List of `{variable, value_selector}` mapping names into the template |

Output: `output`. Useful as an "assembler" and as the cheapest retry-safe way to
build a long prompt from several branches.

## question-classifier

| Field | Notes |
|---|---|
| **`query_variable_selector`** | `[node_id, key]` of the text to classify |
| **`model`** | Model config |
| **`classes`** | Array of `{id, name, label}` — **not** `categories` |
| `instruction` | Classification guidance |
| `memory` | `{query_prompt_template, window: {enabled, size}}` |
| `vision` | `{enabled, configs: {variable_selector: []}}` |

Out-edges use each class's `id` as `sourceHandle`.

> **No else branch.** When the model's answer cannot be matched, the node falls back
> to the **first** class (`question_classifier_node.py::_resolve_category` returns
> `rendered_classes[0]`). Order classes so the first one is a sensible catch-all —
> typically a "general" class.

Outputs: `class_name` · `class_id` · `usage`.

## parameter-extractor

| Field | Notes |
|---|---|
| **`model`** | Model config |
| **`query`** | Selector `[node_id, key]` — **not** `query_variable_selector` |
| **`parameters`** | Array of `{name, type, description, required, options}` |
| **`reasoning_mode`** | `function_call` · `prompt` |
| `instruction` | Extraction guidance |
| `memory` / `vision` | As on `llm` |

`parameters[].type` ∈ `string` · `number` · `select` · `array[string]` ·
`array[number]` · `array[object]` · `array[boolean]`.

Outputs: one key per parameter, plus `__is_success` and `__reason` — check
`__is_success` before trusting the extracted values.

## http-request

| Field | Notes |
|---|---|
| **`method`** | `get` `post` `put` `patch` `delete` `head` `options` (upper-case also accepted) |
| **`url`** | Endpoint. `{{env.X}}` and `{{#node.key#}}` are both allowed |
| **`authorization`** | `{type, config}`; `type` ∈ `no-auth` · `api-key` |
| **`headers`** | Raw string, `Key: Value` per line. Empty is `""` |
| **`params`** | Raw query string. Empty is `""` |
| `body` | `{type, data: [{key, value, type}]}`; `type` ∈ `none` `json` `form-data` `x-www-form-urlencoded` `raw-text` `binary` |
| `timeout` | `{connect, read, write}` in seconds |
| `ssl_verify` | bool |

`headers` and `params` being **required strings** (not optional/nullable) is a 1.17
change worth remembering — omitting them fails validation.

Body rows are either literal (`type: text`) or a variable (`type: variable`, with
`value` holding a `[node, key]` selector).

Outputs: `body` · `status_code` · `headers` · `files`.

## tool

| Field | Notes |
|---|---|
| **`provider_id`** | Plugin/provider id, e.g. `langgenius/google/google` |
| **`provider_type`** | `plugin` · `builtin` · `workflow` · `api` · `app` · `dataset-retrieval` · `mcp` |
| **`provider_name`** | Provider name as registered |
| **`tool_name`** / **`tool_label`** | Tool id and display label |
| **`tool_configurations`** | Provider-side settings (`{name: {type, value}}`) |
| **`tool_parameters`** | Per-call inputs (`{name: {type: variable|constant|mixed, value}}`) |
| `credential_id` | Required when the tool needs a credential — must exist in the workspace |
| `plugin_unique_identifier` | Plugin package id, e.g. `langgenius/google:0.0.5@<hash>` |

Outputs are tool-defined (the node also exposes `files`); check the tool's schema.
Because credentials and identifiers are workspace-specific, **a tool node generated
without access to the target workspace should be treated as a scaffold** — the first
import must re-select the tool in the UI.

## agent

| Field | Notes |
|---|---|
| **`agent_strategy_provider_name`** | e.g. `langgenius/agent/agent` |
| **`agent_strategy_name`** | Strategy the installed plugin declares — `ReAct` / `FunctionCalling` for the official agent plugin |
| **`agent_strategy_label`** | Display label |
| **`agent_parameters`** | Map of `{name: {type, value}}` |
| `memory` | `{query_prompt_template, window: {enabled, size}}` |
| `tool_node_version` | Optional |

Standard `agent_parameters` keys: `model` (constant → model config), `tools`
(constant → array of `{provider_name, tool_name, params, enabled, credential_id}`),
`instruction` (mixed), `query` (mixed), `maximum_iterations` (constant).

Outputs are strategy-defined; the official ReAct/FunctionCalling strategies surface
`text`.

> Dify 1.17 also has an **Agent v2 / agent-chat** app mode (`core.workflow.nodes.agent_v2`)
> whose node data is shaped differently and discriminated by
> `is_dify_agent_node_data`. Do not hand-mix the two shapes in one graph.

## variable-aggregator

| Field | Notes |
|---|---|
| **`variables`** | Array of `[node_id, output_key]` **pairs** — not objects |
| **`output_type`** | `string` · `number` · `object` · `array[object]` · `array[string]` · `any` |
| `advanced_settings` | `{group_enabled: false, groups: []}` |

```yaml
    variables:
      - [code_parse, risks]
      - [code_judge, risks]
    output_type: array[object]
    advanced_settings:
      group_enabled: false
      groups: []
```

Output: `output`.

> The classic `{variable, value_selector}` object form belongs to 0.x and older
> tutorials; 1.17 rejects it. And read the aggregator note in `pitfalls.md` before
> ordering the list — it returns the **first non-empty** value, where `[]` counts as
> non-empty.

## assigner — variable writer

Node type is **`assigner`** (the older `variable-assigner` kind is a legacy
aggregator alias and takes aggregator fields).

| Field | Notes |
|---|---|
| **`items`** | Array of `{variable_selector, input_type, operation, value}` |

`input_type` ∈ `variable` · `constant`. `operation` ∈ `over-write` · `clear` ·
`append` · `extend` · `set` · `+=` · `-=` · `*=` · `/=` · `remove-first` ·
`remove-last`.

```yaml
- data:
    type: assigner
    title: 记录用户名
    desc: ''
    selected: false
    items:
      - variable_selector: [conversation, user_name]
        input_type: variable
        operation: over-write
        value: [start, name]
```

Output: `output`. Targets are `conversation.<name>` or `env.<name>`.

## document-extractor

| Field | Notes |
|---|---|
| **`variable_selector`** | Points at a file / file-list, e.g. `[sys, files]` or `[start, upload]` |

Output: `text` (a string, or an array of strings for a file list). Works for
PDF/DOCX/TXT/MD/CSV/HTML via Dify's built-in extractor; a scanned PDF with no text
layer yields empty output — run OCR upstream.

## list-operator

| Field | Notes |
|---|---|
| **`variable`** | Selector of the array to operate on |
| **`filter_by`** | `{enabled, conditions}` |
| **`order_by`** | `{enabled, key, value}`; `value` ∈ `asc` · `desc` |
| **`limit`** | `{enabled, size}` |
| `extract_by` | `{enabled, serial}` — pick one element by index (1-based string) |

Output: `result`. Handy for turning an array into a single item before an LLM node,
or for taking the top-N of a retrieval result.

## iteration

See `dsl-schema.md` §4 for the full container layout — membership is expressed by
`parentId` + `data.isInIteration` + the inner `iteration-start` node, not by edges
alone.

| Field | Notes |
|---|---|
| **`start_node_id`** | Id of the inner start node |
| **`iterator_selector`** | `[node_id, key]` of the array to iterate |
| **`output_selector`** | `[body_node_id, key]` collected once per item |
| `is_parallel` | Run items concurrently |
| `parallel_nums` | Concurrency cap (default 10) |
| `error_handle_mode` | `terminated` · `continue-on-error` · `remove-abnormal-output` |
| `flatten_output` | Flatten array results into one level |

Outputs: `output` (collected results) plus `item` / `index` readable **inside** the
body as `{{#<iteration_id>.item#}}` and `{{#<iteration_id>.index#}}`.

## loop

| Field | Notes |
|---|---|
| **`start_node_id`** | Id of the inner `loop-start` |
| **`loop_count`** | Maximum rounds |
| **`break_conditions`** | Conditions evaluated between rounds |
| **`logical_operator`** | `and` · `or` |
| `loop_variables` | `{label, var_type, value_type: variable|constant, value}` — state carried between rounds |

Needs both a `loop-start` and a `loop-end` child.

## datasource

Node type `datasource` — a knowledge-pipeline entry point that pulls from a
configured source. Fields are source-specific; prefer authoring it in the UI.
Its data includes the pipeline-specific system variables (`document_id`, `batch`,
`dataset_id`, `datasource_type`, `datasource_info`).

## human-input

Node type `human-input` — pauses a run for a person to fill a form. Implemented in
Dify 1.17's HITL flow (`core/workflow/nodes/human_input`); the form definition lives
in the node's extended data and is easiest to author in the UI.

## triggers — `trigger-webhook` / `trigger-schedule` / `trigger-plugin`

Trigger nodes start a workflow from outside the run API. They are the only other
node kinds allowed as a graph entry (`_START_NODE_TYPES` in `node_factory.py`,
alongside `start` and `datasource`).

- `trigger-schedule` carries a `config` block (cron-style), overwritten with the
  default on export.
- `trigger-webhook` carries `webhook_url` / `webhook_debug_url`, cleared on export
  — the URL is re-issued on import.
- `trigger-plugin` carries a `subscription_id`, also cleared on export.

Because those fields are blanked when exported, a trigger node cannot be faithfully
reproduced from an exported file; configure it in the UI after import.

---

## Failure-branch handles

Any node can opt into error branching via `error_strategy: fail-branch`
(pydantic field on every node data model; values `fail-branch` / `default-value`).
A node with `fail-branch` exposes two out-edges distinguished by `sourceHandle`:
`success-branch` and `fail-branch`. Use it when a flaky HTTP or LLM node should route
to a recovery path instead of failing the run.

## Choosing a node

| Need | Node |
|---|---|
| Prompt an LLM | `llm` |
| Ground an answer in documents | `knowledge-retrieval` + `llm.context` |
| Branch on a value | `if-else` |
| Route on free-text intent | `question-classifier` |
| Extract typed fields from text | `parameter-extractor` |
| Transform data / parse JSON | `code` |
| Assemble a string | `template-transform` |
| Call an API | `http-request` |
| Call a plugin tool | `tool` |
| Let a model choose tools and iterate | `agent` |
| Merge branches | `variable-aggregator` |
| Persist chat state | `assigner` + conversation variables |
| Read an uploaded file | `document-extractor` |
| Pick / sort / filter array items | `list-operator` |
| Loop over a list | `iteration` |
| Retry until a condition holds | `loop` |
| Start from a webhook or cron | `trigger-webhook` / `trigger-schedule` |
