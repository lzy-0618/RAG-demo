# Dify 1.17 DSL schema

Authoritative reference for the file format Dify 1.17 actually imports. Everything
here was verified against `langgenius/dify-api:1.17.0` — the export path
(`services/app_dsl_service.py::export_app`) and the pydantic node models the
runtime validates against (`graphon.nodes.*.entities`,
`core.workflow.nodes.*.entities`).

> **Why this file exists.** Most Dify DSL examples online — and in older versions
> of this skill — show a *different* format. If you write that format, Dify still
> accepts the import (it is lenient about unknown keys) but the canvas renders
> broken nodes and variables do not resolve. The differences are structural, not
> cosmetic. Follow this file, not your memory.

## 1. Top level

```yaml
app:
  name: My Workflow
  mode: workflow                # workflow | advanced-chat | completion | chat | agent-chat
  icon: 🤖                      # emoji, or a URL when icon_type is image
  icon_type: emoji
  icon_background: '#FFEAD5'
  description: What this app does.
  use_icon_as_answer_icon: false

dependencies: []                # plugin/package dependencies (see §7)
kind: app                       # ALWAYS literally "app"
version: 0.7.0                  # current DSL version on 1.17

workflow:
  conversation_variables: []    # chatflow state, see §5
  environment_variables: []     # {{env.X}}, see §5
  features: { ... }             # see §6
  graph:
    nodes: [ ... ]
    edges: [ ... ]
    viewport: {x: 0, y: 0, zoom: 0.7}
```

| Field | Notes |
|---|---|
| `kind` | Must be `app`. It is **not** `app-kind`. Dify rewrites any other value to `app` on import (`app_dsl_service.py`), so writing `app-kind` only makes the file misleading. |
| `version` | 1.17's `CURRENT_APP_DSL_VERSION` is `0.7.0`. A lower *minor* imports as `COMPLETED_WITH_WARNINGS`; a lower *major*, or a higher version than the server, lands in `PENDING`. **Dify performs no migration** — a file claiming `0.1.5` still has to contain a structurally valid 1.17 graph. Write `0.7.0`. |
| `app.mode` | `workflow` ends with an `end` node; `advanced-chat` (chatflow) ends with `answer`. This choice changes which terminal node you need. |
| `dependencies` | Required key in real exports. Empty list is normal for built-in-only apps. |

## 2. Node envelope

Every node — no exceptions — looks like this:

```yaml
- data:
    type: llm                 # <-- the semantic node kind lives HERE
    title: LLM 回答
    desc: ''
    selected: false
    # ... node-type-specific fields, see node-types.md
  height: 200
  id: llm_answer              # unique; this is what selectors reference
  position: {x: 400, y: 300}
  positionAbsolute: {x: 400, y: 300}
  selected: false
  sourcePosition: right
  targetPosition: left
  type: custom                # <-- ALWAYS "custom"
  width: 244
```

The two things people get wrong:

1. **Top-level `type` is `custom` for every node.** The actual node kind is
   `data.type`. The frontend looks up its React renderer by the top-level `type`,
   and `custom` is the key for "render whatever `data.type` says". Writing
   `type: llm` produces a node the frontend cannot render.
2. **`data` needs `title` / `desc` / `selected`.** They are frontend render inputs,
   not decoration.

Container bookkeeping nodes (`iteration-start`, `loop-start`, `loop-end`) are the
one exception: they are ReactFlow *children* and use their own renderer keys
(`custom-iteration-start`, `custom-loop-start`, `custom-loop-end`) plus `parentId`,
`extent: parent`, `draggable: false`, `selectable: false` and a **relative**
`position` — no `positionAbsolute`, no node-level `selected`. See §4.

## 3. Edge envelope

```yaml
- data:
    isInIteration: false
    isInLoop: false
    sourceType: llm          # must equal the source node's data.type
    targetType: answer       # must equal the target node's data.type
  id: edge-llm-answer
  source: llm_answer
  sourceHandle: source       # branch id for if-else / question-classifier
  target: answer
  targetHandle: target
  type: custom
  zIndex: 0
```

`sourceType` / `targetType` duplicate information that is already in the nodes, but
the frontend reads them for edge styling — keep them accurate.

**Branch handles.** For `if-else` the handle is the case's `case_id`; the implicit
else branch is the literal string `false`. For `question-classifier` it is each
class's `id`. All other node types use `source` / `target`.

```
if_route --(sourceHandle: "premium")--> llm_premium     # case_id "premium"
if_route --(sourceHandle: "false")  --> llm_standard    # the else branch
classifier --(sourceHandle: "sales")--> agent_sales     # class id "sales"
```

## 4. Containers — iteration and loop

An iteration container and its body live in the **same** `nodes` array. Membership
is expressed three ways at once, and the engine needs all of them:

```yaml
# The container
- data:
    type: iteration
    title: 逐条处理
    desc: ''
    selected: false
    start_node_id: iter_itemsstart     # id of the inner start node
    iterator_selector: [code_split, items]
    output_selector: [llm_item, text]  # output of one body execution
    is_parallel: true
    parallel_nums: 5
    error_handle_mode: continue-on-error
    flatten_output: true
  id: iter_items
  width: 808
  height: 204
  zIndex: 1
  type: custom
  # ... position / selected etc.

# The inner start (ReactFlow child)
- data:
    type: iteration-start
    title: ''
    desc: ''
    selected: false
    isInIteration: true
  draggable: false
  extent: parent
  id: iter_itemsstart
  parentId: iter_items
  position: {x: 60, y: 78}
  selectable: false
  type: custom-iteration-start
  zIndex: 1002

# A body node
- data:
    type: llm
    isInIteration: true
    iteration_id: iter_items
    # ... normal llm fields
  id: llm_item
  parentId: iter_items
  # ...
```

Rules:

- `start_node_id` must point at the container's inner start node.
- The **inner start must have a real outgoing edge** to the first body node.
  The engine expands the container by walking outward from `start_node_id`, so
  without that edge the body never runs. Inner edges carry
  `data.isInIteration: true` (or `isInLoop`).
- Body nodes carry `parentId` plus `data.isInIteration` / `data.iteration_id`
  (`isInLoop` / `loop_id` for loops).
- Inside the body, read the current element as `{{#<container_id>.item#}}`.
- `loop` additionally needs a `loop-end` child (`type: custom-loop-end`) — the
  body runs start → … → end and the break condition is tested between rounds.

There is no edge from the container node into the inner start; the containment is
structural, not a wire.

## 5. Variables

### Environment variables (`{{env.X}}`)

```yaml
workflow:
  environment_variables:
    - name: EMAIL_API_KEY        # NOT "variable"
      value: ""
      value_type: secret         # string | secret | number | integer | float | boolean | object
                                 # | array[string] | array[number] | array[object] | array[boolean] | array[file]
      description: Optional note
```

`value_type: secret` is masked in the UI and blanked on export unless
`include_secret=true`.

> The key is **`name`**. The backend factory
> (`factories/variable_factory.py::build_environment_variable_from_mapping`) raises
> `VariableError("missing name")` otherwise. The widely-copied `variable:` key is
> wrong and the import fails.

### Conversation variables (chatflow only)

```yaml
workflow:
  conversation_variables:
    - name: user_name
      value: ''
      value_type: string
```

Also keyed by `name`. Read with `{{conversation.user_name}}`; write with an
`assigner` node. They persist across turns of one conversation.

### System variables (`sys.*`)

Always referenced as `[sys, key]` in selectors and `{{#sys.query#}}` in text.

| Key | Meaning |
|---|---|
| `query` | The user's message (chatflow) or the run input |
| `files` | Uploaded files |
| `conversation_id`, `user_id`, `dialogue_count`, `app_id` | Session identity |
| `workflow_id`, `workflow_run_id`, `timestamp` | Run identity |
| `document_id`, `batch`, `dataset_id`, `datasource_type`, `datasource_info` | Set only in knowledge-pipeline context |
| `invoke_from` | What triggered the run |

### Node outputs

Referenced as `[node_id, output_key]` in node data (selectors) and
`{{#node_id.output_key#}}` in prompt text. Output keys per node kind are listed in
`node-types.md`.

## 6. `features`

The frontend reads this block for chat behaviour. A complete, safe default:

```yaml
features:
  file_upload:
    enabled: false
    allowed_file_extensions: []
    allowed_file_types: []
    allowed_file_upload_methods: []
    number_limits: 3
    fileUploadConfig:
      audio_file_size_limit: 50
      batch_count_limit: 5
      file_size_limit: 15
      image_file_size_limit: 10
      video_file_size_limit: 100
      workflow_file_upload_limit: 10
    image:
      enabled: false
      number_limits: 3
      transfer_methods: [local_file, remote_url]
  opening_statement: ''
  retriever_resource:
    enabled: false        # set true on chat apps whose answers cite retrieved chunks
  sensitive_word_avoidance: {enabled: false}
  speech_to_text: {enabled: false}
  suggested_questions: []
  suggested_questions_after_answer: {enabled: false}
  text_to_speech: {enabled: false, language: '', voice: ''}
```

`retriever_resource.enabled` is a **separate switch** from the
`knowledge-retrieval` node: without it, citations exist in the run log but the chat
UI shows no source cards.

## 7. `dependencies`

Populated when the graph references plugin-provided things. For apps built only
from built-in nodes it is `[]`. A tool node contributes an entry like:

```yaml
dependencies:
  - type: marketplace
    value:
      marketplace_plugin_unique_identifier: langgenius/google:0.0.5@<hash>
```

Leave it `[]` when in doubt and let Dify prompt on import — an incorrect hash is
worse than an absent list.

## 8. Export / import

- Studio: `...` → **Export DSL** (`include_secret` optional).
- API: `GET /v1/apps/{app_id}/export?include_secret=false`.
- Import: Studio `...` → **Import DSL**, or `POST /v1/apps/import`.

Import status (`services/dsl_version.py::check_version_compatibility`):

| Condition | Status |
|---|---|
| `imported.major < current.major` | `pending` |
| `imported > current` | `pending` |
| `imported.minor < current.minor` | `completed_with_warnings` |
| otherwise | `completed` |

Dify does **not** transform the graph on import. `include_secret=false` blanks
secret values and drops tool `credential_id`s, so those must be re-entered after
importing an exported file.

## 9. Validating

```bash
python scripts/validate_dsl.py app.yml        # envelope + grammar lint
bash scripts/validate.sh                      # + Dify's own pydantic models
```

`validate.sh` copies the DSL into a running Dify API container and validates each
node's `data` against the same models the runtime uses. That is the strongest check
available without importing, and it catches envelope errors that a hand-written
linter would miss. See `pitfalls.md` for what each error means.
