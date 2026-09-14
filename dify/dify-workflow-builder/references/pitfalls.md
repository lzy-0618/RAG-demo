# Pitfalls

Symptom → cause → fix. Everything here comes from DSL that either failed to import
or — worse — imported fine and then misbehaved at run time.

## 1. The format traps

The single biggest failure mode. Dify accepts the "generic" DSL format most examples
use, because node data models allow extra keys, then renders broken nodes because the
frontend could not find a matching renderer.

| Symptom | Wrong (tutorials / old DSL) | Right (1.17) |
|---|---|---|
| Node shows as an empty/unknown box on the canvas | `type: llm` at node top level | `type: custom` + `data.type: llm` |
| Import succeeds but settings panels are empty | `data` has only type-specific fields | add `data.title` / `data.desc` / `data.selected` |
| All nodes pile up at the origin | no `position` / `positionAbsolute` | both present on every node |
| Edges render as untyped lines, branches mis-route | no `sourceHandle` / `targetHandle` | `source` / `target`, or the case/class id on branch edges |
| `variables` rejected | aggregator `variables: [{variable, value_selector}]` | `variables: [[node_id, output], ...]` |
| Import error `missing name` | env/conversation var key `variable:` | key `name:` |
| Import lands in `pending` | `version` major ≠ server major | `version: 0.7.0` |
| Code node ignores `language` | `language: python3` | `code_language: python3` |
| Code node output unusable | `outputs: {x: {type, value}}` | `outputs: {x: {children: null, type: string}}` |
| End node rejected | `outputs: [{value: {type, value}}]` | `outputs: [{variable, value_type, value_selector}]` |
| Classifier has no accessible field | `categories` | `classes` |
| Extractor rejects config | `query_variable_selector` | `query` |
| HTTP node refuses to import | omitted `headers` / `params` | both required strings, `""` when unused |

## 2. Variable aggregator returns the first *non-empty* value

**Symptom.** A branch correctly finds 3 risks; the app returns `risks: []` and the
run looks clean. A dangerous false negative in compliance/audit flows.

**Cause.** The aggregator picks the first entry whose value is non-empty — and an
empty **array** `[]` counts as non-empty while an unset variable does not. Listing a
source that always executes (and always returns `[]`) ahead of the branch-specific
source masks the real result.

**Fix.** Order `variables` so branch-specific sources come first:

```yaml
# Both ran; code_judge always produces [] on the branch where it ran.
# Correct order: the branch that produced real data first.
variables:
  - [code_parse, risks]   # populated only on the "non-compliant" branch
  - [code_judge, risks]   # ran earlier, returns [] here
output_type: array[object]
```

If the semantics you want is "first non-null, including empty arrays" you have to say
so explicitly — the aggregator will not.

## 3. Model names must be ones the plugin declares

**Symptom.** Requests take 30+ seconds and burn thousands of tokens; the JSON you
asked for is buried in `<think>…</think>` text; `temperature` seems ignored.

**Cause.** The provider plugin normalises completion params only for model names it
declares. An undeclared name is passed through untouched, so provider defaults leak
in — DeepSeek, for example, silently turns **thinking mode on**, ignoring your
`thinking: false`, and writes the reasoning chain into `llm.text`.

**Fix.** Use a declared name (`deepseek-v4-flash`, `deepseek-v4-pro`, `gpt-4o`, …)
and set params explicitly. See `llm-providers.md` for the per-provider list.

## 4. Code nodes must tolerate a thinking chain

**Symptom.** `json.loads(llm_output)` throws, or parses an example object that the
model quoted inside its reasoning rather than the real answer.

**Cause.** Even with thinking disabled, a model may emit a reasoning block, and the
classic `text[text.find('{'):text.rfind('}')+1]` slice swallows the thinking text
along with the answer.

**Fix.** Strip thinking blocks, then scan candidate objects **from the end** and take
the last one containing the key you need:

```python
import json
import re

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def extract_json(text: str, required_key: str):
    text = THINK_RE.sub("", text or "")
    for start in reversed([i for i, ch in enumerate(text) if ch == "{"]):
        depth, in_str, escape = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
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
                    if isinstance(data, dict) and required_key in data:
                        return data
                    break
    return None
```

Always give the node a fallback output plus a `parse_error` flag, and surface the flag
in the `end` outputs. A parse failure that silently becomes "no problems found" is the
worst outcome in an audit workflow.

## 5. JSON answers get truncated at `max_tokens`

**Symptom.** A long input yields `finish_reason: length`, unparseable JSON, and a
silently empty risk list — while the shorter "judge" step had already detected a
problem.

**Fix, all three together:**

1. Raise `max_tokens` on the JSON-producing node (4096 → **8192** for analysis over
   multi-thousand-character inputs).
2. Constrain the prompt: cap item counts and field lengths, and require one complete
   valid JSON object.
3. Expose a `parse_error` flag through the `end` node so the caller can mark the item
   as failed-for-review instead of passing it.

Never rely on `max_tokens` alone; the flag is what makes failure visible.

## 6. Version numbers do not migrate anything

`version: 0.1.5` (the most-copied value) imports as `completed_with_warnings`. Dify
performs **no** structural migration — the graph must already be 1.17-shaped. Write
`0.7.0`; if you inherit an old file, fix its structure rather than its version string.

## 7. Chatflow vs workflow terminal nodes

- `mode: advanced-chat` → the user sees output only from **`answer`** nodes. An `end`
  node ends the run with nothing rendered.
- `mode: workflow` → exactly one **`end`** node.

`answer` supports streaming and multiple bubbles; `end` produces a single JSON
response for API callers.

## 8. The classifier has no else branch

When no class matches, `question-classifier` falls back to the **first** class in
`classes`. Put your catch-all ("general", "other") first, or accept that unmatched
input silently takes the first route.

Only `if-else` has a real `false` branch. Do not look for a `false` handle on a
classifier.

## 9. Retrieval needs two independent switches

- `features.retriever_resource.enabled: true` → chat UI shows source cards.
- The `knowledge-retrieval` node → actually searches.

Forgetting the first gives correct answers with no citations; forgetting the second
gives citations from nothing. Reranking is a third switch
(`multiple_retrieval_config.reranking_enable`) and needs a reranker model configured
in the workspace, otherwise it is quietly skipped. Hybrid search without a reranker
often returns weakly related chunks (scores around 0.03 in practice) — turn reranking
on for Chinese or mixed-language corpora.

## 10. Dataset ids, credentials and triggers do not survive an export

`include_secret=false` (the default) blanks secret env values and strips tool
`credential_id`s; knowledge-retrieval `dataset_ids` are re-encrypted per workspace;
webhook/schedule triggers have their URLs and subscription ids cleared.

So an exported DSL is a **structure**, not a deployable artifact. After importing, the
checklist is: bind datasets, re-pick tool credentials, re-enter secrets, reconfigure
triggers. Say this explicitly in any deployment guide you write.

## 11. Orphan nodes and dead branches

The runtime executes by graph traversal from `start`, so a node with no inbound edge
never runs — no error, no warning, just missing output. The usual cause is reordering
an aggregator or forgetting an edge in a branch.

`validate_dsl.py` warns about nodes unreachable from `start` and about aggregator
sources that can never be populated. Heed the warnings; a workflow that "runs fine"
with an unreachable node is producing wrong results.

Note the exception: container bodies (`iteration` / `loop` children) are reached from
`start_node_id`, not by a top-level edge, so they are not orphans. The validator knows
the difference.

## 12. Sandbox limits inside `code`

Dify's code sandbox has no network access and only allow-listed packages. `import
requests`, `pandas` or `numpy` fails at run time unless the wheel is enabled in the
sandbox config *and* pinned in the node's `dependencies`. Standard library only is the
safe default; push anything heavier into an `http-request` node.

Also: the entrypoint must be `def main(...) -> dict`, and every declared `outputs` key
must be present in the returned dict.

## 13. Credentials never belong in the DSL

`validate_dsl.py` fails on `sk-…`, `AKIA…`, `ghp_…`, `xox…` patterns and on JWT-shaped
strings. Put values in environment variables (`{{env.X}}`, declared under
`workflow.environment_variables`), or better, in the workspace credential store for
tool nodes. A DSL is committed to git; secrets in it are leaked.
