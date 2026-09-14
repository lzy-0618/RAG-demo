# Knowledge base and RAG

Dify's knowledge base (called a **dataset** in the DSL and API) does the retrieval; the
`knowledge-retrieval` node wires it into a workflow.

## 1. Indexing technique

Chosen at dataset creation, not in the DSL:

| Value | Behaviour |
|---|---|
| `high_quality` | Embeds chunks into a vector index — slower to build, best retrieval |
| `economy` | Keyword index only, no embedding — fast, adequate for small corpora |

The valid strings are exactly `high_quality` and `economy`
(`models/dataset.py::Dataset.INDEXING_TECHNIQUE_LIST`). `economic` is not accepted.

## 2. Chunking

Set in the dataset's process rule. Defaults that work well for policy/contract text:

- automatic segmentation on
- max chunk length ~500–1000 tokens, 50–100 token overlap
- **parent-child** retrieval when documents are long and structured: index small
  child chunks for matching but hand the parent chunk to the LLM, which keeps clause
  context without bloating `top_k`

Keep the original clause/heading in the chunk text where you can — answers that cite
"第X条" depend on the number surviving chunking.

## 3. The `knowledge-retrieval` node

```yaml
- data:
    type: knowledge-retrieval
    title: 知识检索
    desc: ''
    selected: false
    query_variable_selector: [code_rewrite, question]
    dataset_ids: []                    # [] is valid: bind in the UI after import
    retrieval_mode: multiple           # multiple | single
    multiple_retrieval_config:
      top_k: 5
      score_threshold: null
      reranking_enable: true
      reranking_mode: reranking_model
      reranking_model:
        provider: langgenius/siliconflow/siliconflow
        model: BAAI/bge-reranker-v2-m3
      weights: null
    metadata_filtering_mode: disabled  # disabled | automatic | manual
    vision:
      enabled: false
      configs:
        variable_selector: []
```

Notes that bite:

- `dataset_ids: []` imports fine and is the honest way to ship a template — the ids are
  workspace-specific and re-encrypted per workspace, so a hardcoded id from another
  instance is useless.
- `reranking_enable: true` needs a reranker model configured as a workspace model
  provider, otherwise it silently does nothing.
- `retrieval_mode: single` uses `single_retrieval_config.model` (a model config, not a
  vector search) — a rarely useful path for workflow retrieval.

Output: `result`, an array of segment objects.

```json
[
  {"content": "the chunk text", "title": "source title", "score": 0.87,
   "metadata": {"document_id": "...", "dataset_id": "..."}}
]
```

## 4. Feeding retrieval into an LLM

Two ways. **Preferred:** attach it to the model node's `context`, which formats the
segments and exposes them as `{{#context#}}`:

```yaml
- data:
    type: llm
    context:
      enabled: true
      variable_selector: [retriever, result]
    prompt_template:
      - role: user
        text: "Context:\n{{#context#}}\n\nQuestion:\n{{#sys.query#}}"
```

**Manual:** reshape with a `template-transform` when you need control over formatting:

```yaml
- data:
    type: template-transform
    template: |
      {% for doc in result %}
      [{{ doc.title }}] (score {{ doc.score }})
      {{ doc.content }}
      ---
      {% endfor %}
    variables:
      - variable: result
        value_selector: [retriever, result]
```

## 5. Citation cards

`features.retriever_resource.enabled` must be `true` for the chat UI to render source
cards next to an answer:

```yaml
features:
  retriever_resource:
    enabled: true
```

This is a **separate switch** from the retrieval node. With it off, retrieval still
works and the run log still records the chunks — the user just sees no sources.

## 6. Tuning

| Knob | Guidance |
|---|---|
| `top_k` | 3–6 for factual Q&A; 10–20 only for synthesis tasks where the model must merge many sources |
| `score_threshold` | Start `null` (return top-K regardless) and tighten once you have seen real scores. Thresholds are model-specific — a value tuned on one embedding model mis-filters on another |
| `reranking_enable` | Turn on for anything high-stakes or multilingual. Hybrid/vector search alone often returns weakly related chunks (scores near 0.03 have been observed on Chinese policy text) |
| reranker choice | Cross-encoder rerankers (`BAAI/bge-reranker-v2-m3`, Cohere `rerank-multilingual-v3.0`) handle Chinese well |
| query rewriting | A small model that turns a follow-up ("那住宿标准呢") into a standalone query before retrieval is usually the single biggest quality win in multi-turn apps — see `templates/rag-qa.yml` and the customer-service example |

## 7. Multi-dataset retrieval

One node can search several datasets — list them all in `dataset_ids`. Dify retrieves
from each and merges before reranking, so a single node over
[regulations, internal policy, precedents] gives the reranker a unified candidate pool.
That is usually better than several nodes plus a `variable-aggregator`, which would give
you two already-truncated result sets to merge by hand.

Use separate nodes only when the datasets need *different* `top_k`, thresholds, or
rerankers.

## 8. Guardrails worth adding

- **Answer only from context.** Instruct the model to say "not in the knowledge base"
  when the context is empty, and to cite sources. Ungrounded answers are the main
  failure mode of RAG assistants.
- **Surface the failure.** If your prompt asks for JSON, run it through a code node that
  emits a `parse_error` flag and expose that flag in the `end` node. Silent parse
  failures become silent false negatives — see `pitfalls.md` §4–5.
- **Keep retrieval and generation failures distinguishable.** A retrieval miss and a
  generation refusal look identical to a user; log or return the retrieved chunk count
  so you can tell them apart.

## 9. Dataset API (for seeding from CI)

```bash
# Create a dataset
curl -X POST "$DIFY_API/v1/datasets" \
  -H "Authorization: Bearer $DATASET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Company Handbook","indexing_technique":"high_quality","permission":"only_me"}'

# Upload a file into it
curl -X POST "$DIFY_API/v1/datasets/$DATASET_ID/document/create_by_file" \
  -H "Authorization: Bearer $DATASET_API_KEY" \
  -F 'data={"indexing_technique":"high_quality","process_rule":{"mode":"automatic"}}' \
  -F 'file=@handbook.pdf'
```

Then paste the returned dataset id into `dataset_ids`.
