# Customer Service Bot

A multi-turn support chatflow that rewrites follow-up questions into standalone search
queries before retrieving, which is the single biggest quality win in a conversational
RAG app.

## What it does

1. User asks a question, possibly a follow-up that only makes sense in context
   ("那住宿标准呢" / "and the limit for that?").
2. `llm_rewrite` uses the conversation window to rewrite it into a standalone query,
   with `temperature: 0` and a "output the query only" instruction.
3. `knowledge-retrieval` searches with that rewritten query (top 4, reranked).
4. `llm_answer` answers from the retrieved context, cites sources, and escalates
   explicitly when the material does not cover the question.
5. `answer` streams the reply.

## Graph

```
start ─> llm_rewrite (llm, memory) ─> retriever (knowledge-retrieval) ─> llm_answer (llm, memory) ─> answer
```

5 nodes, 4 edges. `mode: advanced-chat`.

Note the retrieval query is `[llm_rewrite, text]`, not `[sys, query]` — that is the whole
point of the first node.

## Files

- `dsl.yml` — the DSL, ready to import (Dify 1.17, `version: 0.7.0`)
- `README.md` — this file

## Setup

1. **Create the knowledge base** with your support content (FAQs, policy, product docs),
   indexing technique **High Quality**.
2. **Import** `dsl.yml` as a chatflow.
3. **Bind the dataset** on `知识检索`, and make sure a reranker model is configured in the
   workspace since `reranking_enable: true`.
4. **Configure the models.** Both LLM nodes default to `gpt-4o-mini`. Keep the rewrite
   node small, fast and at `temperature: 0`; the answer node can be a step up.
5. Test a two-turn conversation where the second message is a bare follow-up.

## Test cases

| Turn | Input | Expected |
|---|---|---|
| 1 | "What is the business travel accommodation standard?" | Grounded answer with citations |
| 2 | "And for a manager?" | Rewritten to a standalone query (visible in the run log as `llm_rewrite.text`), then answered correctly |
| 3 | "Can I get a discount?" | Refusal to promise anything unverifiable, plus a request for the details needed to escalate |

The turn-2 case is the one to watch: if the answer is wrong, inspect
`llm_rewrite.text` in the run trace. If the rewrite is not standalone, the retrieval query
was bad, not the answering model.

## Notes

- Both LLM nodes enable `memory` with a window of 10 — the rewrite node needs it to
  resolve pronouns, and the answer node needs it for conversational continuity.
- Add a `code` node after `llm_rewrite` if your model sometimes returns a full sentence of
  commentary instead of just the query. Strip `<think>…</think>` and fall back to
  `{{#sys.query#}}` when the rewrite is empty (`../../references/pitfalls.md` §4).
- For a rule-heavy escalation path, add an `if-else` on the rewritten query and route to a
  human-handoff `http-request` node instead of trying to solve everything in the prompt.
