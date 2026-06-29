#!/usr/bin/env python3
"""
iMessage bridge — minimal HTTP server that sends via Messages.app (AppleScript).

Endpoints:
  GET  /health        → {"status": "ok"}
  POST /send          → {"recipient": "+1...", "content": "..."}
               ← {"status": "sent", "message_id": "<uuid>"}

Run:
  python imessage_bridge.py          # port 8001 (default)
  python imessage_bridge.py 8002     # custom port
"""

import json
import subprocess
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


def send_imessage(recipient: str, content: str) -> None:
    script = f"""
tell application "Messages"
    set targetService to first service whose service type = iMessage
    set targetBuddy to buddy "{recipient}" of targetService
    send "{content.replace('"', '\\"').replace(chr(10), "\\n")}" to targetBuddy
end tell
"""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "AppleScript error")


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[bridge] {self.address_string()} - {format % args}")

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/send":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        recipient = body.get("recipient") or body.get("phone")
        content = body.get("content") or body.get("message") or body.get("body")

        if not recipient or not content:
            self._send_json(400, {"error": "recipient and content are required"})
            return

        try:
            send_imessage(recipient, content)
            self._send_json(200, {"status": "sent", "message_id": str(uuid.uuid4())})
        except Exception as e:
            print(f"[bridge] ERROR: {e}")
            self._send_json(500, {"error": str(e)})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    server = HTTPServer(("127.0.0.1", port), BridgeHandler)
    print(f"iMessage bridge listening on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBridge stopped.")
