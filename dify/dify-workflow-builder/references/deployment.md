# Deploying and importing

## 1. Run Dify locally

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env          # set SECRET_KEY and the DB/Redis passwords
docker compose up -d
docker compose logs -f api
```

Studio: <http://localhost/install> (first-run setup) · API: <http://localhost/v1>

Minimum: Docker 20.10+, Compose v2, 2 CPU / 4 GB RAM (8 GB with local models), ~20 GB
disk.

**Note the API container's name** — the validation script needs it. Compose names it
`docker-api-1` by default, which is what `scripts/validate.sh` looks for; override with
`DIFY_CONTAINER=<name> bash scripts/validate.sh` if yours differs.

## 2. Before importing: validate

```bash
python scripts/validate_dsl.py my-app.yml     # envelope + grammar
bash scripts/validate.sh my-app.yml           # + Dify's own pydantic models
```

`validate.sh` copies the file into the running `dify-api` container and validates each
node's `data` against the exact model the runtime uses. Run this **before** importing —
it turns "the canvas looks wrong" into a named error.

## 3. Import

### Studio (most reliable)

1. Studio → **Create from blank** → choose the app kind matching `app.mode`.
2. Save it.
3. `...` → **Import DSL File** → pick the `.yml`.
4. Review the warnings Dify reports (`completed_with_warnings` is normal when the
   file's `version` is below `0.7.0`).

### Console API

Import lives on the **console** API, not the service API — it authenticates with a
console session cookie, not an app API key:

```bash
POST /console/api/apps/imports
{
  "mode": "yaml-content",          # or "yaml-url"
  "yaml_content": "<the DSL as a string>",
  "name": "Optional override",
  "app_id": "Optional: import over an existing app"
}
```

Responses: `200` completed, `202` pending confirmation (major-version mismatch or
missing plugin dependencies), `400` failed. A `202` must be confirmed via
`POST /console/api/apps/imports/{import_id}/confirm`, and missing dependencies are
checked with `POST /console/api/apps/imports/{app_id}/check-dependencies`. Getting a
console session cookie outside the browser is fiddly, so scripted imports are usually
done by driving the Studio UI instead.

For running the imported app from code you use the **service** API with an app key
(Studio → API Access):

```bash
# Chatflow
curl -X POST "$DIFY/v1/chat-messages" \
  -H "Authorization: Bearer app-xxxx" -H "Content-Type: application/json" \
  -d '{"inputs":{},"query":"hello","response_mode":"blocking","user":"u-1"}'

# Workflow
curl -X POST "$DIFY/v1/workflows/run" \
  -H "Authorization: Bearer app-xxxx" -H "Content-Type: application/json" \
  -d '{"inputs":{"contract_text":"..."},"response_mode":"blocking","user":"u-1"}'
```

## 4. After importing — the mandatory checklist

A DSL file is a **structure, not a deployment**. The import blanks or invalidates
everything workspace-specific. Walk this list every time:

| Step | Why |
|---|---|
| Bind `dataset_ids` on every `knowledge-retrieval` node | Dataset ids are encrypted per workspace; a value from another instance is meaningless |
| Fill environment variables under `...` → Environment Variables | Secrets are exported blank (`include_secret=false`), and non-secret defaults are often placeholders |
| Re-select credentials for every `tool` and `agent` node | `credential_id` is stripped on export and is workspace-specific |
| Install missing plugins | `202 pending` on import usually means an uninstalled plugin; dependencies are listed in the import result |
| Re-select the agent strategy | `agent_strategy_name` must exist in the installed agent plugin, or the node is dead |
| Reconfigure trigger nodes | Webhook URLs and subscription ids are cleared by design |
| Open the canvas once | Catches layout/rendering problems that a structural check cannot see (the fastest way to confirm `type: custom` vs `data.type` is right) |

## 5. Model providers

Each provider needs its plugin installed **and** a credential configured before a node
referencing it will run.

| Provider | Setup |
|---|---|
| OpenAI | Settings → Model Provider → OpenAI → paste key |
| Anthropic | Marketplace → Anthropic → Install → paste `ANTHROPIC_API_KEY` |
| DeepSeek | Marketplace → DeepSeek → Install → paste key from platform.deepseek.com |
| Ollama | `ollama serve` on the host, then `OLLAMA_API_BASE_URL=http://host.docker.internal:11434` in Dify's `.env`, then restart |
| Xinference (local embeddings) | `XINFERENCE_BASE_URL=http://host.docker.internal:9997` |

Verify the **model names** in the dropdown before writing them into a DSL — see
`llm-providers.md` for why an undeclared name is worse than an error.

## 6. Operating

```bash
docker compose logs -f api          # API
docker compose logs -f worker       # async runs
docker compose logs -f db redis
```

Studio → **Logs & Annotations** shows every run with inputs, outputs, timings and the
per-node trace. This is the first place to look when a run "succeeds" but the answer is
wrong — an empty node output is invisible in the final response.

### Backup

```bash
docker compose exec -T db pg_dump -U postgres dify > backup.sql
cat backup.sql | docker compose exec -T db psql -U postgres dify   # restore
```

### Scaling

```bash
# In .env
CELERY_WORKER_AMOUNT=2
docker compose up -d --scale worker=4
```

## 7. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Import returns `202 pending` | Major-version mismatch or missing plugin dependencies; confirm via the confirm endpoint after installing plugins |
| `completed_with_warnings` | `version` below `0.7.0`. Harmless **if** the graph is genuinely 1.17-shaped; the warning is not a migration |
| Canvas shows blank/unknown nodes | Node envelope wrong — top-level `type` must be `custom` with the kind in `data.type` (see `dsl-schema.md` §2) |
| "Provider not found" | Plugin not installed, or the `provider` id does not match the installed plugin |
| LLM returns empty or slow, JSON buried in reasoning text | Undeclared model name: params were passed through unnormalised (`pitfalls.md` §3) |
| RAG returns nothing | Dataset empty/unindexed, or `dataset_ids` unbound after import |
| Citations missing in chat | `features.retriever_resource.enabled` is false (`pitfalls.md` §9) |
| Node never runs | Unreachable from `start`; the validator warns about this |
| HTTP node 401 | Credential not in `headers`; there is no `bearer` authorization type |
| Workflow hangs | `http-request` without a `timeout` |
| Agent loops or overspends | Lower `maximum_iterations`, tighten the instruction, reduce the toolset |

## 8. Production checklist

- [ ] Rotate `SECRET_KEY` and all database/Redis passwords off the sample values
- [ ] HTTPS in front (nginx + Let's Encrypt)
- [ ] External Postgres, Redis and vector DB instead of the bundled containers
- [ ] Object storage (S3/OSS) for uploaded files
- [ ] Backups scheduled and a restore actually rehearsed
- [ ] Log rotation and retention configured
- [ ] Every environment variable recorded in a secret manager, not only in the Dify UI
- [ ] A smoke test that runs each published app through the service API on deploy —
      structural validation cannot tell you a model credential expired
