#!/usr/bin/env bash
# Start the MCP server and an HTTPS tunnel. The packaged settings UMD is served
# from the same public origin, so edit drawers work without RDS or a CDN.
#
# Usage:
#   ./run_with_tunnel.sh
#   ./run_with_tunnel.sh your-domain.ngrok-free.app

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPOSITORY_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORT="${PORT:-8000}"
NGROK_DOMAIN="${1:-}"
TUNNEL_LOG="$(mktemp -t workflow-mcp-tunnel.XXXXXX)"

cleanup() {
  echo
  echo "Stopping MCP server and tunnel..."
  for process_id in "${TAIL_PID:-}" "${API_PID:-}" "${TUNNEL_PID:-}"; do
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
      kill "$process_id" 2>/dev/null || true
    fi
  done
  rm -f "$TUNNEL_LOG"
}
trap cleanup EXIT INT TERM

start_tunnel() {
  if command -v cloudflared >/dev/null 2>&1; then
    TUNNEL_PROVIDER="cloudflared"
    cloudflared tunnel --protocol http2 --url "http://localhost:$PORT" \
      >"$TUNNEL_LOG" 2>&1 &
  elif command -v ngrok >/dev/null 2>&1; then
    TUNNEL_PROVIDER="ngrok"
    if [[ -n "$NGROK_DOMAIN" ]]; then
      ngrok http --url="$NGROK_DOMAIN" "$PORT" >"$TUNNEL_LOG" 2>&1 &
    else
      ngrok http "$PORT" >"$TUNNEL_LOG" 2>&1 &
    fi
  else
    TUNNEL_PROVIDER="localhost.run"
    ssh -o ServerAliveInterval=60 -R 80:localhost:"$PORT" nokey@localhost.run \
      >"$TUNNEL_LOG" 2>&1 &
  fi
  TUNNEL_PID=$!
}

read_public_url() {
  local detected_url=""

  if [[ "$TUNNEL_PROVIDER" == "ngrok" ]]; then
    detected_url="$(./.venv/bin/python -c \
      'import json, urllib.request; data=json.load(urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1)); print(next((item["public_url"] for item in data.get("tunnels", []) if item.get("public_url", "").startswith("https://")), ""))' \
      2>/dev/null || true)"
  fi

  if [[ -z "$detected_url" ]]; then
    detected_url="$(grep -Eo 'https://[[:alnum:].-]+' "$TUNNEL_LOG" \
      | grep -E '(trycloudflare\.com|ngrok[^/]*\.(app|io)|lhr\.life|localhost\.run)$' \
      | tail -n 1 || true)"
  fi

  printf '%s' "$detected_url"
}

echo "1) Starting HTTPS tunnel..."
start_tunnel

PUBLIC_URL=""
for _attempt in $(seq 1 45); do
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[ERROR] $TUNNEL_PROVIDER exited before producing a public URL." >&2
    cat "$TUNNEL_LOG" >&2
    exit 1
  fi
  PUBLIC_URL="$(read_public_url)"
  if [[ -n "$PUBLIC_URL" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[ERROR] Could not discover the tunnel URL after 45 seconds." >&2
  cat "$TUNNEL_LOG" >&2
  exit 1
fi

# This launcher is deliberately self-contained. Ignore any stale CDN/RDS value
# from .env and bind the app payload + CSP to the tunnel serving this checkout.
export WORKFLOW_SETTINGS_RUNTIME_URL="$PUBLIC_URL/assets/workflow-settings-runtime.js"

echo "2) Starting MCP server on port $PORT..."
./.venv/bin/python api.py &
API_PID=$!
sleep 2

if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "[ERROR] MCP server exited during startup." >&2
  exit 1
fi

echo
echo "Ready. Keep this terminal open:"
echo "  Connector URL: $PUBLIC_URL/mcp"
echo "  Settings UMD:  $WORKFLOW_SETTINGS_RUNTIME_URL"
echo

# Keep later tunnel diagnostics visible while the API process owns the script.
tail -n 0 -f "$TUNNEL_LOG" &
TAIL_PID=$!
wait "$API_PID"
