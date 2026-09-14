#!/usr/bin/env bash
# Run the Dify 1.17 DSL validator with Dify's OWN pydantic node models.
#
# The grammar lint in validate_dsl.py runs anywhere, but the authoritative check
# needs `graphon` / `core`, which only exist inside the Dify API container. This
# wrapper copies the validator plus the DSL files into that container and runs
# them there.
#
# Usage:
#   bash scripts/validate.sh                     # every DSL under ./templates ./examples
#   bash scripts/validate.sh app.yml [more.yml]  # specific files
#   DIFY_CONTAINER=my-api-1 bash scripts/validate.sh
#
# The container name is auto-detected from `docker ps` when not set explicitly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for container validation; falling back to grammar lint" >&2
  exec python3 "$SCRIPT_DIR/validate_dsl.py" "$@"
fi

detect_container() {
  # Prefer an explicit env var, then the conventional compose service name, then any
  # running dify-api image.
  if [ -n "${DIFY_CONTAINER:-}" ]; then
    echo "$DIFY_CONTAINER"
    return
  fi
  local running
  running="$(docker ps --format '{{.Names}}\t{{.Image}}' 2>/dev/null || true)"
  if printf '%s\n' "$running" | grep -q '^docker-api-1'; then
    echo "docker-api-1"
    return
  fi
  local match
  match="$(printf '%s\n' "$running" | awk -F'\t' '/dify-api/ {print $1; exit}')"
  if [ -n "$match" ]; then
    echo "$match"
    return
  fi
  echo ""
}

CONTAINER="$(detect_container)"
if [ -z "$CONTAINER" ]; then
  echo "no running Dify API container found; running grammar lint only" >&2
  exec python3 "$SCRIPT_DIR/validate_dsl.py" "$@"
fi

# Which files to check: explicit args, else the shipped DSL corpus.
files=()
if [ "$#" -gt 0 ]; then
  for f in "$@"; do files+=("$f"); done
else
  while IFS= read -r f; do files+=("$f"); done < <(
    {
      find "$SKILL_DIR/templates" "$SKILL_DIR/examples" -name '*.yml' -o -name '*.yaml' 2>/dev/null
      [ -f "$SKILL_DIR/dify-rag-bot.yml" ] && echo "$SKILL_DIR/dify-rag-bot.yml"
    } | sort
  )
fi

if [ "${#files[@]}" -eq 0 ]; then
  echo "no DSL files to validate" >&2
  exit 1
fi

# Stage the script and its sibling library so the import of dify_dsl resolves.
#
# Two hazards shape this:
#   * The script's own directory becomes sys.path[0], so anything left next to it can
#     shadow a module the Dify runtime imports. Use a unique directory per run and wipe
#     it afterwards, so nothing accumulates.
#   * `docker cp` writes as root, while the container normally runs as a non-root user
#     that cannot delete those files. A fixed path therefore breaks on the second run;
#     a unique path sidesteps that, and cleanup is best-effort.
STAGE="/tmp/dslcheck-$$-$(date +%s)"
cleanup() {
  docker exec -u 0 "$CONTAINER" rm -rf "$STAGE" >/dev/null 2>&1 \
    || docker exec "$CONTAINER" rm -rf "$STAGE" >/dev/null 2>&1 \
    || true
}
trap cleanup EXIT

docker exec "$CONTAINER" mkdir -p "$STAGE" >/dev/null
docker cp "$SCRIPT_DIR/validate_dsl.py" "$CONTAINER:$STAGE/validate_dsl.py" >/dev/null
docker cp "$SCRIPT_DIR/dify_dsl.py" "$CONTAINER:$STAGE/dify_dsl.py" >/dev/null

# Stage under a unique name per file: several examples are all called dsl.yml, and a flat
# copy would silently overwrite each other so only the last one got checked.
staged=()
index=0
for f in "${files[@]}"; do
  index=$((index + 1))
  # Keep the parent directory in the name so each file stays identifiable in the report.
  parent="$(basename "$(dirname "$f")")"
  name="${index}-${parent}-$(basename "$f")"
  docker cp "$f" "$CONTAINER:$STAGE/$name" >/dev/null
  staged+=("$STAGE/$name")
done

USE_PY="python3"
if docker exec "$CONTAINER" test -x /app/api/.venv/bin/python 2>/dev/null; then
  USE_PY="/app/api/.venv/bin/python"
fi

# PYTHONDONTWRITEBYTECODE keeps __pycache__ out of the staging directory.
docker exec -w /app/api -e PYTHONPATH="/app/api:$STAGE" -e PYTHONDONTWRITEBYTECODE=1 "$CONTAINER" \
  "$USE_PY" "$STAGE/validate_dsl.py" "${staged[@]}"
