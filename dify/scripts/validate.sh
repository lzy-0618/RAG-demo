#!/usr/bin/env bash
# 校验 dify/dsl/ 下的所有 DSL 文件（用 Dify 容器内的 pydantic 模型）。
# 用法：bash dify/scripts/validate.sh [容器名，默认 docker-api-1]
set -euo pipefail

CONTAINER="${1:-docker-api-1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

docker cp "$ROOT/dify/scripts/validate_dsl.py" "$CONTAINER:/tmp/validate_dsl.py" >/dev/null

files=()
for f in "$ROOT"/dify/dsl/*.yml; do
  [ -e "$f" ] || continue
  name="$(basename "$f")"
  docker cp "$f" "$CONTAINER:/tmp/$name" >/dev/null
  files+=("/tmp/$name")
done

if [ ${#files[@]} -eq 0 ]; then
  echo "dify/dsl/ 下没有 DSL 文件" >&2
  exit 1
fi

docker exec -w /app/api -e PYTHONPATH=/app/api "$CONTAINER" \
  /app/api/.venv/bin/python /tmp/validate_dsl.py "${files[@]}"
