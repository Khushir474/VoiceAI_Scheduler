#!/usr/bin/env bash
set -e

USER_ID="${1:-00000000-0000-0000-0000-000000000001}"
PORT=8888
NGROK_BIN="${NGROK_BIN:-$(command -v ngrok 2>/dev/null || echo /opt/homebrew/bin/ngrok)}"
NGROK_PID=""
SERVER_PID=""

cleanup() {
  [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null
  [[ -n "$NGROK_PID" ]] && kill "$NGROK_PID" 2>/dev/null
}
trap cleanup EXIT

ROOT="$(dirname "$0")/.."
ENV_FILE="$ROOT/backend/.env"

# ── 1. Start ngrok ────────────────────────────────────────────────────────────
echo "▶ Starting ngrok..."
pkill -f "ngrok http $PORT" 2>/dev/null || true
"$NGROK_BIN" http "$PORT" --log=stdout > /tmp/ngrok_dailyops.log 2>&1 &
NGROK_PID=$!

# Wait for ngrok API to be ready (up to 10s)
for i in $(seq 1 20); do
  NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
    | python3 -c "import sys,json; t=json.load(sys.stdin).get('tunnels',[]); print(next((x['public_url'] for x in t if x['public_url'].startswith('https')), ''))" 2>/dev/null)
  [[ -n "$NGROK_URL" ]] && break
  sleep 0.5
done

if [[ -z "$NGROK_URL" ]]; then
  echo "✗ ngrok failed to start. Check /tmp/ngrok_dailyops.log"
  cat /tmp/ngrok_dailyops.log
  exit 1
fi

TOOL_URL="${NGROK_URL}/api/daily-context"
echo "✓ ngrok tunnel: $NGROK_URL"

# ── 2. Update VAPI_TOOL_SERVER_URL in backend/.env ───────────────────────────
if grep -q "VAPI_TOOL_SERVER_URL" "$ENV_FILE"; then
  sed -i '' "s|VAPI_TOOL_SERVER_URL=.*|VAPI_TOOL_SERVER_URL=${TOOL_URL}|" "$ENV_FILE"
else
  echo "VAPI_TOOL_SERVER_URL=${TOOL_URL}" >> "$ENV_FILE"
fi
echo "✓ VAPI_TOOL_SERVER_URL set to $TOOL_URL"

# ── 3. Start backend server ───────────────────────────────────────────────────
echo "▶ Starting server..."
cd "$ROOT/backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" 2>&1 &
SERVER_PID=$!

until curl -sf "http://localhost:$PORT/health" > /dev/null; do sleep 0.5; done
echo "✓ Server ready"

# ── 4. Trigger the run ────────────────────────────────────────────────────────
echo "▶ Triggering run for user $USER_ID..."
curl -s -X POST "http://localhost:$PORT/api/test-run?user_id=$USER_ID" | python3 -m json.tool

echo ""
echo "✓ Done — call should be incoming"

# Keep server + ngrok alive so Vapi can POST tool calls back
echo "(Press Ctrl+C to stop)"
wait "$SERVER_PID"
