# Model configuration

An `llm`, `knowledge-retrieval` (reranker), `question-classifier`,
`parameter-extractor` or `agent` node all carry a model block:

```yaml
model:
  provider: langgenius/openai/openai   # plugin id
  name: gpt-4o                          # a model the plugin DECLARES
  mode: chat                            # chat | completion
  completion_params:                    # provider-specific; free-form map
    temperature: 0.3
    max_tokens: 2048
```

`ModelConfig` requires `provider`, `name`, `mode`. `completion_params` is a free-form
map — Dify does not validate the param names, which is exactly why a wrong `name` is
dangerous (see below).

## The one rule that matters most

**Use a model name the installed plugin declares.** Dify only normalises completion
parameters for names it recognises; an unrecognised name is forwarded verbatim to the
provider, so provider defaults leak in and your params are silently discarded.

Observed in practice with the DeepSeek plugin: an undeclared name (`deepseek-chat`
when the plugin exposes only `deepseek-v4-flash` / `deepseek-v4-pro`) means

- `thinking: false` is ignored — **thinking mode stays on**;
- one classification call took ~4400 completion tokens and 28 seconds;
- `temperature` is discarded (thinking mode overrides it);
- the reasoning chain is written into `llm.text` as `<think>…</think>`, drowning the
  JSON answer you asked for.

So: pick the name from the workspace's model dropdown, then set the params you want
explicitly:

```yaml
model:
  provider: langgenius/deepseek/deepseek
  name: deepseek-v4-flash
  mode: chat
  completion_params:
    thinking: false
    temperature: 0.1
    max_tokens: 8192
    response_format: json_object      # only on nodes that must emit JSON
```

## Provider ids

| Provider | `provider` |
|---|---|
| OpenAI | `langgenius/openai/openai` |
| Anthropic | `langgenius/anthropic/anthropic` |
| DeepSeek | `langgenius/deepseek/deepseek` |
| 通义千问 Qwen | `langgenius/tongyi/tongyi` |
| 智谱 GLM | `langgenius/zhipuai/zhipuai` |
| 月之暗面 Moonshot | `langgenius/moonshot/moonshot` |
| 百度千帆 | `langgenius/baidu/baidu` |
| 火山方舟 / 豆包 | `langgenius/volcengine/volcengine` |
| 腾讯混元 | `langgenius/tencent_hunyuan/tencent_hunyuan` |
| Groq | `langgenius/groq/groq` |
| Mistral | `langgenius/mistralai/mistralai` |
| Cohere | `langgenius/cohere/cohere` |
| Ollama (local) | `langgenius/ollama/ollama` |
| LocalAI | `langgenius/localai/localai` |
| Xinference | `langgenius/xinference/xinference` |
| Any OpenAI-compatible endpoint | `langgenius/openai_api_compatible/openai_api_compatible` |

Plugin ids drift between releases and each plugin exposes its own model list. **Verify
against the workspace** (Settings → Model Provider) rather than trusting this table,
and never invent a model name — a plausible-looking name that the plugin does not
declare is the failure mode described above.

## `completion_params` that are broadly safe

| Param | Notes |
|---|---|
| `temperature` | 0–2. Ignored while a reasoning model's thinking mode is on |
| `top_p` | 0–1 |
| `max_tokens` | Cap on output. Set it on every node that must return JSON |
| `response_format` | `text` · `json_object` — supported by OpenAI-style APIs and DeepSeek |
| `stop` | Array of stop strings |
| `presence_penalty` / `frequency_penalty` | OpenAI-compatible only |
| `seed` | Deterministic sampling where supported |
| `thinking` | DeepSeek plugin's reasoning switch; **set `false`** for structured output |

Reasoning models are a trap for structured output: the reasoning chain shares
`max_tokens` with the answer, so a long chain can truncate the JSON. Disable thinking
where the plugin allows it, and read `finish_reason` / `reasoning_content` when
debugging.

## Model choice by job

| Job | Reasonable default |
|---|---|
| Deterministic classification / extraction | a small fast model at `temperature: 0` with `response_format: json_object` |
| Judgment and analysis over long text | a strong model at low temperature, `max_tokens` ≥ 8192 |
| Free-form drafting | mid-size model, temperature 0.4–0.8 |
| Follow-up-query rewriting for retrieval | small model, temperature 0, `max_tokens` ~256 |
| Local / private deployment | Ollama, e.g. `qwen2.5:7b` (see below) |

## Ollama and other local runtimes

Dify runs in containers, so `localhost` means *the container*. Point it at the host:

```bash
# Dify's .env
OLLAMA_API_BASE_URL=http://host.docker.internal:11434
```

On Linux use the Docker bridge address (`http://172.17.0.1:11434`) or the host's LAN
IP. Then reference the model normally:

```yaml
model:
  provider: langgenius/ollama/ollama
  name: qwen2.5:7b
  mode: chat
  completion_params:
    temperature: 0.3
    max_tokens: 2048
```

## Embeddings and rerankers are configured outside the DSL

Embedding and rerank models are selected when the **knowledge base** is created or in
the `knowledge-retrieval` node's `multiple_retrieval_config`, not in the model block of
a chat node:

```yaml
multiple_retrieval_config:
  top_k: 5
  score_threshold: null
  reranking_enable: true
  reranking_mode: reranking_model
  reranking_model:
    provider: langgenius/siliconflow/siliconflow
    model: BAAI/bge-reranker-v2-m3
  weights: null
```

A reranker must be configured as a model provider in the workspace first, otherwise
`reranking_enable: true` is quietly a no-op. Multilingual corpora (Chinese in
particular) do noticeably better with a cross-encoder reranker than with hybrid search
alone — see `knowledge-rag.md`.

## Routing between models

Because `model` is per node, routing is structural: fan out with
`question-classifier` or `if-else` and give each branch its own model, then merge.

```
classifier ──(technical)──> llm_strong   (large model, detailed answer)
           ──(general)────> llm_fast     (small model, cheap answer)
                          └> variable-aggregator ─> answer
```

There is no `fallback` field in the 1.17 model block. For fallbacks, either branch on
an `http-request` health check or point both branches at a gateway that handles
failover (LiteLLM and similar, via the OpenAI-compatible provider).
