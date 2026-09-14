# Doc Q&A System

A chatflow that answers questions from a knowledge base and can additionally ground its
answer on a document the user uploads in the same turn.

## What it does

1. User optionally uploads a document (PDF / DOCX / MD) with the question.
2. `document-extractor` turns the attachment into text.
3. `knowledge-retrieval` searches the bound datasets (top 4, reranked) using the user's question.
4. The LLM answers from both sources, citing `[Source N]` for knowledge-base chunks and
   `[Uploaded doc]` for the attachment, and says so when neither covers the question.
5. `answer` streams the reply; `features.retriever_resource` is on so source cards render.

## Graph

```
start ─┬─> extract_doc (document-extractor) ─┐
       │                                      ├─> llm_answer (llm) ─> answer
       └─> retriever (knowledge-retrieval) ───┘
```

5 nodes, 5 edges. `mode: advanced-chat`, so the reply goes out through `answer` (not `end`).

## Files

- `dsl.yml` — the DSL, ready to import (Dify 1.17, `version: 0.7.0`)
- `README.md` — this file

## Setup

1. Start Dify (see `../../references/deployment.md`).
2. **Create the knowledge base**: Studio → Knowledge → Create Dataset → indexing
   technique **High Quality** → choose an embedding model → upload your documents →
   wait for indexing.
3. **Import** `dsl.yml`: Studio → Create from blank (chatflow) → save → `...` → Import DSL File.
4. **Bind the dataset**: open `知识检索`, select your dataset in `dataset_ids`
   (`dataset_ids: []` in the file is intentional — dataset ids are workspace-specific).
5. **Configure the model**: the LLM node references `langgenius/openai/openai` /
   `gpt-4o`. Point it at a provider you have configured, or re-run the generator:
   `python ../../scripts/generate_dsl.py -t rag-qa --llm-model deepseek-flash`.
   If you use DeepSeek, keep `thinking: false` — otherwise the reasoning chain lands in
   `llm.text` and pollutes the answer.
6. **Confirm file upload is enabled** for the chat. The `start` node declares an optional
   `upload` file input; the app's file-upload feature must be on for the UI to show the
   control.
7. Copy the app's API key if you want to call it from code, then test.

## Test cases

| Input | Expected |
|---|---|
| "What is the travel expense limit?" (no upload) | Grounded answer with `[Source N]` citations |
| Same question + an uploaded policy PDF | Answer cites `[Uploaded doc]` alongside or instead of knowledge-base sources |
| A question the corpus does not cover | Explicit "the knowledge base has no relevant entry" rather than an invented answer |

## Notes

- Without `features.retriever_resource.enabled: true` the retrieval still works but no
  source cards appear in the chat UI — see `../../references/pitfalls.md` §9.
- A scanned PDF with no text layer yields empty `extract_doc.text`. Run OCR before upload.
- Retrieval quality on Chinese or mixed corpora improves markedly with reranking on; the
  node ships with `reranking_enable: true`, which requires a reranker model configured in
  the workspace.
