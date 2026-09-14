# Variable references

Dify stores a variable reference two ways, and mixing them up is the most common
cause of "the node runs but the value is empty". Both forms are shown below using the
same underlying reference: an LLM node's `text` output.

## 1. Selectors — the form used inside node `data`

Anywhere a node *takes* a value, it is a 2-element array `[node_id, output_key]`:

```yaml
- data:
    type: llm
    context:
      enabled: true
      variable_selector: [retriever, result]     # <-- selector
    prompt_template:
      - role: user
        text: '{{#sys.query#}}'
```

Selector-bearing fields, and the key each lives under:

| Field | Shape |
|---|---|
| `variable_selector` | `[node, key]` — retrieval query, LLM context, node inputs |
| `variables[].value_selector` | `[node, key]` — code / template-transform inputs |
| `condition.variable_selector` | `[node, key]` — if-else and loop conditions |
| `end.outputs[].value_selector` | `[node, key]` |
| `query` (parameter-extractor) | `[node, key]` — note the different key name |
| `variable` / `iterator_selector` / `output_selector` (list-operator, iteration) | `[node, key]` |
| `variable_aggregator.variables[]` | `[[node, key], [node, key], …]` — a list of pairs |
| `assigner.items[].variable_selector` | `[node, key]` |
| HTTP body row with `type: variable` | `value: [node, key]` |
| HTTP request `params` / `headers` | raw strings, use `{{#node.key#}}` inside |

Because a selector names the **producing node**, you cannot reference a value that no
upstream node produces — and Dify does not always tell you clearly. `validate_dsl.py`
checks every selector against the producing node's real output keys.

## 2. `{{#node.key#}}` — the form used inside text

Prompt templates, templates, HTTP headers/URLs, and `answer` text are strings, so they
use the hash-wrapped form:

```yaml
text: '依据：{{#retriever.result#}}'
```

Rules:

- Upstream node outputs: **always** `{{#node_id.output_key#}}` with the `#` on both
  sides.
- `{{#context#}}` is special: it is the retrieval context attached via
  `llm.context`. It has **no node id**.
- System variables are `{{#sys.query#}}`, `{{#sys.files#}}`, … (see below).
- Environment variables are `{{env.NAME}}` — bare, no hashes.
- Conversation variables are `{{conversation.name}}` — bare, no hashes.

Inside an iteration body, the current element is `{{#<iteration_id>.item#}}` and the
round index is `{{#<iteration_id>.index#}}`.

## 3. System variables

| Selector | Meaning |
|---|---|
| `[sys, query]` / `{{#sys.query#}}` | The user's message, or the run input |
| `[sys, files]` | Uploaded files |
| `[sys, conversation_id]`, `[sys, user_id]`, `[sys, dialogue_count]`, `[sys, app_id]` | Session identity |
| `[sys, workflow_id]`, `[sys, workflow_run_id]`, `[sys, timestamp]` | Run identity |
| `[sys, document_id]`, `[sys, batch]`, `[sys, dataset_id]`, `[sys, datasource_type]`, `[sys, datasource_info]` | Knowledge-pipeline context only |
| `[sys, invoke_from]` | What triggered the run |

## 4. Environment variables

Declared once at workflow level and referenced with `{{env.NAME}}`:

```yaml
workflow:
  environment_variables:
    - name: SLACK_WEBHOOK        # key is `name`
      value: 'https://hooks.slack.com/services/...'
      value_type: string
    - name: EMAIL_API_KEY
      value: ''
      value_type: secret          # masked in the UI, blanked on export
```

`value_type` ∈ `string` · `secret` · `number` · `integer` · `float` · `boolean` ·
`object` · `array[string]` · `array[number]` · `array[object]` · `array[boolean]` ·
`array[file]`.

Two things to get right:

- The key is **`name`**. `variable:` fails with `missing name` on import.
- Secrets live here, never inline. `validate_dsl.py` fails on `sk-…`, `AKIA…`,
  `ghp_…`, `xox…` and JWT-shaped strings.

## 5. Conversation variables

Chatflow-only state that survives across turns:

```yaml
workflow:
  conversation_variables:
    - name: user_name
      value: ''
      value_type: string
```

Read with `{{conversation.user_name}}`; write with an `assigner` node targeting
`[conversation, user_name]`. Also keyed by `name`.

Unlike environment variables these are per-conversation, and they are reset when the
user starts a new conversation — do not use them for configuration.

## 6. Jinja2 in templates

`template-transform` and `llm` prompts both render Jinja2. Variables declared in the
node's `variables` list are available by bare name (no hashes):

```yaml
- data:
    type: template-transform
    template: |
      Topic: {{ topic }}
      {% if audience %}Audience: {{ audience }}{% endif %}
      {{ items | join(", ") }}
    variables:
      - variable: topic
        value_selector: [start, topic]
      - variable: audience
        value_selector: [start, audience]
      - variable: items
        value_selector: [code_split, items]
```

Handy filters: `join`, `length`, `default`, `upper`, `lower`, `replace`, `trim`.
Access object fields with `{{ row.amount }}` and array indices with `{{ items[0] }}`.

`llm` prompts can do the same, but note that `{{#node.key#}}` references are
substituted *before* Jinja2 runs, so the two syntaxes coexist safely.

## 7. Debugging a reference

1. Check the producing node's real output key (see `node-types.md` — e.g. a
   `template-transform` outputs `output`, a `knowledge-retrieval` outputs `result`).
2. Run `python scripts/validate_dsl.py app.yml`; it names the node, the key, and the
   keys that node actually produces.
3. A `variable-aggregator` masks problems: an empty result may mean a branch never
   ran, not that the reference is wrong. Read `pitfalls.md` §2.
4. Insert a `template-transform` as a "print" — point it at the variable and inspect
   its output in the run log.
