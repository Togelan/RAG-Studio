from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

HOST: Final = "0.0.0.0"
PORT: Final = 8080
MODEL: Final = "stage3-deterministic"
SLOW_CANCEL_MARKER: Final = "slow-cancel"
SLOW_CANCEL_SECONDS: Final = 5.0


def _messages_text(payload: dict[str, object]) -> str:
    raw_messages = payload.get("messages", [])
    if not isinstance(raw_messages, list):
        return ""
    parts: list[str] = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            continue
        content = raw.get("content", "")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _answer(payload: dict[str, object]) -> str:
    message_text = _messages_text(payload)
    if "intent classifier" in message_text:
        return "standalone"
    if "faithfulness evaluator" in message_text:
        return "1.0"
    return "The Stage 3 deterministic provider completed the local chatbot reply."


def _chunk(payload: dict[str, object], content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-stage3",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None,
            }
        ],
    }


def _stream_chunks(payload: dict[str, object]) -> tuple[dict[str, object], ...]:
    if SLOW_CANCEL_MARKER in _messages_text(payload):
        return (
            _chunk(payload, "Task 11 cancellation fixture started."),
            _chunk(payload, _answer(payload)),
        )
    return (_chunk(payload, _answer(payload)),)


def _completion(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-stage3",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _answer(payload)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class ProviderHandler(BaseHTTPRequestHandler):
    server_version = "Stage3Provider/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        parsed = json.loads(raw or b"{}")
        return parsed if isinstance(parsed, dict) else {}

    def do_GET(self) -> None:
        if self.path.rstrip("/") != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps(
            {"object": "list", "data": [{"id": MODEL, "object": "model"}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404)
            return
        payload = self._json_body()
        if payload.get("stream") is True:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            chunks = _stream_chunks(payload)
            for index, chunk in enumerate(chunks):
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                if index == 0 and len(chunks) > 1:
                    time.sleep(SLOW_CANCEL_SECONDS)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        body = json.dumps(_completion(payload)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    ThreadingHTTPServer((HOST, PORT), ProviderHandler).serve_forever()


if __name__ == "__main__":
    main()
