#!/bin/bash
# Keeps the dev Cloudflare quick tunnels (api:8000, web:3000) alive.
#
# Quick tunnels (trycloudflare.com) don't survive a laptop sleep/wake cycle:
# the underlying connection drops but the cloudflared process doesn't exit,
# it just loops forever logging "Unauthorized: Tunnel not found" against a
# URL that will never work again. This script health-checks each tunnel,
# restarts the dead ones (which mints a brand new random URL), and syncs
# the new URL(s) into .env (CORS_ALLOW_ORIGINS) and docker-compose.yml
# (NEXT_PUBLIC_API_URL), recreating only the containers that need it.
#
# Intended to run on a short interval via launchd (see
# scripts/com.signalforge.tunnel-watchdog.plist) so recovery is automatic.
set -euo pipefail

REPO_DIR="/Users/sandeepjadhav/Desktop/stock-analyst"
STATE_DIR="/private/tmp/sf-tunnels"
LOCK_DIR="${STATE_DIR}/watchdog.lock"
WATCHDOG_LOG="${STATE_DIR}/watchdog.log"

mkdir -p "$STATE_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >>"$WATCHDOG_LOG"; }

is_healthy() {
  local url="$1"
  [ -n "$url" ] || return 1
  local code
  # Don't `|| echo "000"` here: curl's `-w` already prints "000" itself on
  # a connection failure, AND exits non-zero in that case - combining both
  # concatenates to "000000" (never equal to "000"), which silently made
  # every dead tunnel look healthy. `||` must *replace* code, not append.
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 "$url" 2>/dev/null) || code="000"
  [ "$code" != "000" ]
}

start_tunnel() {
  local name="$1" port="$2"
  local pidfile="${STATE_DIR}/${name}.pid"
  local logfile="${STATE_DIR}/${name}.log"
  local urlfile="${STATE_DIR}/${name}.url"

  if [ -f "$pidfile" ]; then
    local oldpid
    oldpid=$(cat "$pidfile" 2>/dev/null || true)
    [ -n "$oldpid" ] && kill "$oldpid" 2>/dev/null || true
  fi
  pkill -f "cloudflared tunnel --url http://localhost:${port}\$" 2>/dev/null || true
  sleep 1

  : >"$logfile"
  nohup cloudflared tunnel --url "http://localhost:${port}" >"$logfile" 2>&1 &
  local pid=$!
  echo "$pid" >"$pidfile"
  disown "$pid" 2>/dev/null || true

  local url=""
  for _ in $(seq 1 20); do
    url=$(grep -o 'https://[a-zA-Z0-9.-]*trycloudflare.com' "$logfile" | head -1 || true)
    [ -n "$url" ] && break
    sleep 1
  done

  if [ -z "$url" ]; then
    log "ERROR: ${name} tunnel did not produce a URL in time"
    return 1
  fi

  echo "$url" >"$urlfile"
  log "${name}: started new tunnel -> ${url}"
  echo "$url"
}

API_URL=""
WEB_URL=""
API_CHANGED=0
WEB_CHANGED=0

API_URLFILE="${STATE_DIR}/api.url"
WEB_URLFILE="${STATE_DIR}/web.url"

OLD_API_URL=$(cat "$API_URLFILE" 2>/dev/null || true)
if is_healthy "$OLD_API_URL"; then
  API_URL="$OLD_API_URL"
else
  API_URL=$(start_tunnel api 8000) || exit 1
  API_CHANGED=1
fi

OLD_WEB_URL=$(cat "$WEB_URLFILE" 2>/dev/null || true)
if is_healthy "$OLD_WEB_URL"; then
  WEB_URL="$OLD_WEB_URL"
else
  WEB_URL=$(start_tunnel web 3000) || exit 1
  WEB_CHANGED=1
fi

if [ "$API_CHANGED" -eq 0 ] && [ "$WEB_CHANGED" -eq 0 ]; then
  exit 0
fi

cd "$REPO_DIR"

if [ "$API_CHANGED" -eq 1 ]; then
  sed -i '' -E "s#^([[:space:]]*NEXT_PUBLIC_API_URL:).*#\1 ${API_URL}#" docker-compose.yml
fi

if [ "$WEB_CHANGED" -eq 1 ]; then
  sed -i '' -E "s#^CORS_ALLOW_ORIGINS=.*#CORS_ALLOW_ORIGINS=http://localhost:3000,${WEB_URL}#" .env
fi

RECREATE=()
[ "$API_CHANGED" -eq 1 ] && RECREATE+=(web)   # web bakes NEXT_PUBLIC_API_URL in at `next dev` startup
[ "$WEB_CHANGED" -eq 1 ] && RECREATE+=(api)   # api re-reads CORS_ALLOW_ORIGINS from .env at startup

if [ "${#RECREATE[@]}" -gt 0 ]; then
  log "recreating containers: ${RECREATE[*]}"
  docker compose up -d --force-recreate "${RECREATE[@]}" >>"$WATCHDOG_LOG" 2>&1
fi

log "done: api=${API_URL} web=${WEB_URL}"
