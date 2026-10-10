#!/usr/bin/env bash
# RAG_demo 一键重启：停掉在跑的服务 → 重启 Dify → 后端(:8000) → 前端(:5173)
#
# 用法：
#   ./start.command                # 终端里执行，或在 Finder 里双击
#   ./start.command --no-open      # 启动完成后不自动打开浏览器
#
# 可覆盖的环境变量：
#   DIFY_DOCKER_DIR   Dify 的 docker compose 目录（默认见下方 DIFY_DIR）
#   DIFY_RECREATE=1   把 Dify 从容器里彻底重建（down + up -d），默认只 restart
#
# 注意：每次执行都会先停掉正在运行的后端与前端，正在进行的审查/生成任务会被中断。
# 日志与 PID 落在 .run/ 下（.gitignore 已忽略），每次启动覆盖写入，只保留本轮。

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT/.run"
DIFY_DIR="${DIFY_DOCKER_DIR:-$HOME/dify/dify-1.17.0/docker}"
DIFY_CONTAINER="docker-nginx-1"   # compose 目录名是 docker，容器因此带 docker- 前缀
BACKEND_PORT=8000
FRONTEND_PORT=5173
OPEN_BROWSER=1
[ "${1:-}" = "--no-open" ] && OPEN_BROWSER=0

mkdir -p "$RUN_DIR"
FAILED=""

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi
step() { printf '\n%s[%s/5]%s %s\n' "$C_DIM" "$1" "$C_OFF" "$2"; }
ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_OFF" "$1"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_OFF" "$1"; }
fail() { printf '  %s✗%s %s\n' "$C_ERR" "$C_OFF" "$1"; FAILED="$FAILED $1"; }
info() { printf '  %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }

port_owner() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

# 等待 HTTP 就绪：$1=url $2=最长秒数
wait_http() {
  local url="$1" timeout="${2:-60}" waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if curl -s -o /dev/null --max-time 3 "$url"; then return 0; fi
    sleep 2; waited=$((waited + 2))
  done
  return 1
}

# 停服务：优先按 PID 文件，再兜底按端口占用者（PID 文件丢了或进程被替换时），
# 普通信号无效则强杀——否则端口不释放，下一步的「启动」就会误判成失败
stop_service() {
  local name="$1" pidfile="$2" port="$3"
  local pids
  pids="$( { [ -f "$pidfile" ] && cat "$pidfile"; port_owner "$port"; } 2>/dev/null | sort -u | tr '\n' ' ')"
  if [ -z "${pids// /}" ]; then
    ok "$name 未在运行"
    rm -f "$pidfile"
    return 0
  fi
  kill $pids 2>/dev/null
  local waited=0
  while [ "$waited" -lt 15 ] && [ -n "$(port_owner "$port")" ]; do sleep 1; waited=$((waited + 1)); done
  if [ -n "$(port_owner "$port")" ]; then
    warn "$name 未响应普通信号，强制结束"
    kill -9 $(port_owner "$port") 2>/dev/null
    sleep 2
  fi
  if [ -z "$(port_owner "$port")" ]; then
    ok "$name 已停止（PID ${pids% }）"
  else
    fail "$name 停止失败（:$port 仍被占用）"
  fi
  rm -f "$pidfile"
}

printf 'RAG_demo 重启脚本\n'

# ── 1. Docker Desktop ────────────────────────────────────────────────
step 1 "Docker Desktop"
if docker info >/dev/null 2>&1; then
  ok "守护进程已在运行"
else
  warn "未运行，正在打开 Docker Desktop（首次启动可能要 30-60 秒）"
  open -a Docker
  for _ in $(seq 1 60); do
    docker info >/dev/null 2>&1 && break
    sleep 5
  done
  if docker info >/dev/null 2>&1; then ok "守护进程已就绪"; else fail "Docker 启动超时，请手动打开 Docker Desktop 后重跑本脚本"; fi
fi

# ── 2. 停掉在跑的服务 ────────────────────────────────────────────────
step 2 "停止在跑的服务"
stop_service "后端" "$RUN_DIR/backend.pid" "$BACKEND_PORT"
stop_service "前端" "$RUN_DIR/frontend.pid" "$FRONTEND_PORT"

if ! docker info >/dev/null 2>&1; then
  warn "Docker 不可用，跳过 Dify 容器"
elif [ ! -d "$DIFY_DIR" ]; then
  warn "找不到 Dify compose 目录：${DIFY_DIR}（可用 DIFY_DOCKER_DIR 指定）"
else
  # 不用 `docker compose ps -q | grep -q .` 判断是否在运行：开了 pipefail 时 grep 读完
  # 首个匹配就退出，docker compose 拿到 EPIPE 而返回非 0，正常运行也会被误判成「未在运行」。
  # 另：容器引擎刚从休眠唤醒时，compose ps 可能瞬时为空，所以给几次重试。
  dify_running=""
  dify_present=""
  for _ in 1 2 3; do
    dify_running="$(cd "$DIFY_DIR" && docker compose ps -q 2>/dev/null)"
    dify_present="$(cd "$DIFY_DIR" && docker compose ps -aq 2>/dev/null)"
    if [ -n "$dify_running" ] || [ -n "$dify_present" ]; then break; fi
    sleep 2
  done

  if [ -n "$dify_running" ] && [ "${DIFY_RECREATE:-0}" = "1" ]; then
    warn "DIFY_RECREATE=1，彻底重建 Dify 容器（down + up -d）…"
    ( cd "$DIFY_DIR" && docker compose down && docker compose up -d ) >>"$RUN_DIR/dify.log" 2>&1 \
      && ok "Dify 已重建（数据卷保留）" || fail "Dify 重建失败，详见 .run/dify.log"
  elif [ -n "$dify_running" ]; then
    warn "正在重启 Dify 容器（保留数据卷）…"
    ( cd "$DIFY_DIR" && docker compose restart ) >>"$RUN_DIR/dify.log" 2>&1 \
      && ok "Dify 已重启" || fail "Dify 重启失败，详见 .run/dify.log"
  else
    warn "Dify 未在运行，正在启动容器…"
    ( cd "$DIFY_DIR" && docker compose up -d ) >>"$RUN_DIR/dify.log" 2>&1 \
      && ok "Dify 已启动" || fail "Dify 启动失败，详见 .run/dify.log"
  fi
fi

# ── 3. Dify 就绪检查 ─────────────────────────────────────────────────
step 3 "Dify（docker compose）"
if [ ! -d "$DIFY_DIR" ] || ! docker info >/dev/null 2>&1; then
  fail "Dify 不可用（缺少 compose 目录或 Docker 未运行）"
else
  if ! curl -s -o /dev/null --max-time 3 http://localhost/; then
    info "等待容器就绪…"
    wait_http http://localhost/ 180 || fail "Dify 180 秒内未响应，详见 .run/dify.log"
  fi
  if curl -s -o /dev/null --max-time 3 http://localhost/; then
    ok "已就绪（http://localhost）"
    docker ps --filter "name=$DIFY_CONTAINER" --format '  {{.Names}}  {{.Status}}' 2>/dev/null
  fi
fi

# ── 4. 后端 FastAPI ──────────────────────────────────────────────────
step 4 "后端 FastAPI（:${BACKEND_PORT}）"
if [ -x "$ROOT/backend/.venv/bin/python" ]; then
  # 用 `exec` 让子 shell 被目标进程替换掉，PID 文件里记的才是服务本身
  ( cd "$ROOT/backend" && exec nohup ./.venv/bin/python -m uvicorn app.main:app --reload --port "$BACKEND_PORT" \
      >"$RUN_DIR/backend.log" 2>&1 ) &
  echo $! >"$RUN_DIR/backend.pid"
  if wait_http "http://127.0.0.1:$BACKEND_PORT/api/v1/health" 60; then
    ok "已启动（PID $(cat "$RUN_DIR/backend.pid")，日志 .run/backend.log）"
  else
    fail "后端 60 秒内未就绪，详见 .run/backend.log"
  fi
else
  fail "缺少虚拟环境 backend/.venv，请先执行：cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

# ── 5. 前端 Web ──────────────────────────────────────────────────────
step 5 "前端 Web（:${FRONTEND_PORT}）"
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  fail "缺少 frontend/node_modules，请先执行：cd frontend && npm install"
else
  # 直接跑 vite：`npm run dev` 会再套一层 shell，PID 指向 npm 的话，停服务时
  # 杀 npm 不会带走真正的 vite 进程，端口会一直被占着
  if [ -x "$ROOT/frontend/node_modules/.bin/vite" ]; then
    ( cd "$ROOT/frontend" && exec nohup ./node_modules/.bin/vite >"$RUN_DIR/frontend.log" 2>&1 ) &
  else
    ( cd "$ROOT/frontend" && exec nohup npm run dev >"$RUN_DIR/frontend.log" 2>&1 ) &
  fi
  echo $! >"$RUN_DIR/frontend.pid"
  # Vite 默认只监听 localhost（IPv6 ::1），用 127.0.0.1 探测会连不上
  if wait_http "http://localhost:$FRONTEND_PORT/" 60; then
    ok "已启动（PID $(cat "$RUN_DIR/frontend.pid")，日志 .run/frontend.log）"
  else
    fail "前端 60 秒内未就绪，详见 .run/frontend.log"
  fi
fi

# ── 汇总 ─────────────────────────────────────────────────────────────
printf '\n'
if [ -n "$FAILED" ]; then
  printf '%s未全部就绪%s，失败项：%s\n' "$C_ERR" "$C_OFF" "$FAILED"
else
  printf '%s全部就绪%s\n' "$C_OK" "$C_OFF"
fi

printf '\n  前端访问网址   http://localhost:%s\n' "$FRONTEND_PORT"
printf '  后端接口       http://127.0.0.1:%s/api/v1        （接口文档 http://127.0.0.1:%s/docs）\n' "$BACKEND_PORT" "$BACKEND_PORT"
printf '  Dify 接口      http://localhost/v1              （控制台 http://localhost）\n'

cat <<EOF

  种子账号       expert / Expert@2026       专家（可纠错标注）
                 user01 / User@2026         普通用户
  日志           .run/backend.log、.run/frontend.log、.run/dify.log
EOF

if [ "$OPEN_BROWSER" = "1" ] && [ -z "$FAILED" ]; then
  open "http://localhost:$FRONTEND_PORT"
fi

# 双击运行时窗口会在脚本结束后立刻关闭，留一个回车让人看清结果
if [ -t 0 ]; then
  printf '\n按回车键关闭此窗口…'
  read -r _
fi

[ -z "$FAILED" ]
