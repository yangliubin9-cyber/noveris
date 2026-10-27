"""Local OpenAI-compatible mock for manual browser testing only.

Run: python tests/mock_upstream.py --port 8765
It binds to 127.0.0.1 and never invokes a real model.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MODEL_ID = "mock-chat"


class MockModelHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/v1/models":
            self.send_json(200, {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local-mock"}]})
        else:
            self.send_json(404, {"error": {"message": "Not found", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/chat/completions":
            self.send_json(404, {"error": {"message": "Not found", "type": "not_found"}})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("Request body must be 1 byte to 1 MiB")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
                raise ValueError("messages must be an array")
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            return

        prompt = next(
            (message.get("content", "") for message in reversed(body["messages"])
             if isinstance(message, dict) and message.get("role") == "user"),
            "",
        )
        answer = f"本地模拟回复：{prompt}" if isinstance(prompt, str) and prompt else "本地模拟回复。"
        model = body.get("model") or MODEL_ID
        if body.get("stream") is True:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            events = [
                {"id": "chatcmpl-local-mock", "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer}, "finish_reason": None}]},
                {"id": "chatcmpl-local-mock", "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            for event in events:
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self.send_json(200, {
            "id": "chatcmpl-local-mock",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[mock upstream] {self.address_string()} - {format_string % args}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a local OpenAI-compatible mock upstream for manual testing")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), MockModelHandler)
    print(f"Mock upstream listening on http://127.0.0.1:{server.server_port}/v1 (model: {MODEL_ID})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
