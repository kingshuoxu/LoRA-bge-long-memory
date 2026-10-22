"""本地 HTTP 服务。只监听 127.0.0.1，页面和接口同一个源。"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from memory_core.paths import bundle_root, default_home, default_models_dir
from memory_core.service import MemoryService, ServiceError


def ui_dir() -> Path:
    env = os.environ.get("LORA_MEMORY_UI")
    if env:
        return Path(env)
    packaged = bundle_root().parent / "ui"
    if (packaged / "index.html").is_file():
        return packaged
    return bundle_root() / "desktop" / "ui"


TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class App:
    def __init__(self):
        home = Path(os.environ["LORA_MEMORY_HOME"]) if os.environ.get("LORA_MEMORY_HOME") else default_home()
        models = Path(os.environ["LORA_MEMORY_MODELS"]) if os.environ.get("LORA_MEMORY_MODELS") else default_models_dir()
        device = os.environ.get("LORA_MEMORY_DEVICE")
        self.service = MemoryService(home=home, models_dir=models, device=device)
        self.ui = ui_dir()


def _json_bytes(payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body


def make_handler(app: App):
    service = app.service

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 2_000_000:
                raise ServiceError("请求太大")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ServiceError("请求不是 JSON") from exc

        def _serve_file(self, path: Path):
            if not path.is_file():
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            data = path.read_bytes()
            self._send(200, data, TYPES.get(path.suffix.lower(), "application/octet-stream"))

        def _api(self, method: str, parts: list[str], payload: dict):
            if method == "GET" and parts == ["health"]:
                return _json_bytes(service.health())
            if method == "POST" and parts == ["models", "download"]:
                service.start_model_prepare()
                return _json_bytes(service.health())
            if method == "GET" and parts == ["conversations"]:
                return _json_bytes({"conversations": service.list_conversations()})
            if method == "POST" and parts == ["conversations"]:
                return _json_bytes(service.create_conversation(payload.get("title") or "新对话"))
            if len(parts) == 2 and parts[0] == "conversations" and method == "GET":
                return _json_bytes(service.get_conversation(parts[1]))
            if len(parts) == 2 and parts[0] == "conversations" and method == "DELETE":
                service.delete_conversation(parts[1])
                return _json_bytes({"ok": True})
            if len(parts) == 3 and parts[0] == "conversations" and parts[2] == "messages" and method == "POST":
                return _json_bytes(service.send_message(parts[1], payload.get("content", "")))
            if method == "GET" and parts == ["experts"]:
                return _json_bytes({"experts": service.list_experts()})
            if len(parts) == 2 and parts[0] == "experts" and method == "DELETE":
                return _json_bytes(service.delete_expert(parts[1]))
            if method == "POST" and parts == ["consolidate", "preview"]:
                return _json_bytes(service.start_preview(payload.get("conversation_ids") or []))
            if method == "GET" and len(parts) == 3 and parts[0] == "consolidate" and parts[1] == "preview":
                return _json_bytes(service.preview_status(parts[2]))
            if method == "POST" and parts == ["consolidate", "commit"]:
                return _json_bytes({
                    "job": service.start_consolidation(
                        payload.get("conversation_ids") or [],
                        payload.get("facts") or [],
                        preview_id=payload.get("preview_id"),
                    )
                })
            if method == "GET" and parts == ["nebula"]:
                return _json_bytes(service.nebula())
            if method == "POST" and parts == ["corrections", "propose"]:
                return _json_bytes({
                    "proposal": service.propose_correction(
                        payload.get("text") or "",
                        fact_id=payload.get("fact_id"),
                        new_value=payload.get("new_value"),
                    )
                })
            if method == "POST" and parts == ["corrections", "commit"]:
                return _json_bytes({
                    "job": service.commit_correction(
                        payload.get("proposal") or payload,
                        conversation_id=payload.get("conversation_id"),
                    )
                })
            if method == "GET" and parts == ["jobs", "current"]:
                return _json_bytes({"job": service.current_job()})
            if len(parts) == 2 and parts[0] == "jobs" and method == "GET":
                return _json_bytes(service.job_status(parts[1]))
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel" and method == "POST":
                return _json_bytes(service.cancel_job(parts[1]))
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "resume" and method == "POST":
                return _json_bytes(service.resume_job(parts[1]))
            return _json_bytes({"error": "没有这个接口"}, 404)

        def _dispatch(self, method: str):
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/"):
                parts = [item for item in path[len("/api/"):].split("/") if item]
                try:
                    payload = self._read_json() if method in {"POST", "PUT"} else {}
                    status, body = self._api(method, parts, payload)
                except ServiceError as exc:
                    status, body = _json_bytes({"error": str(exc)}, 400)
                except Exception as exc:
                    status, body = _json_bytes({"error": str(exc)}, 500)
                self._send(status, body, "application/json; charset=utf-8")
                return
            if method != "GET":
                self._send(405, b"method", "text/plain; charset=utf-8")
                return
            rel = "index.html" if path in {"", "/"} else path.lstrip("/")
            if ".." in rel.split("/"):
                self._send(400, b"bad path", "text/plain; charset=utf-8")
                return
            self._serve_file(app.ui / rel)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler


def main():
    app = App()
    app.service.start_model_prepare()
    port = int(os.environ.get("LORA_MEMORY_PORT", "8765"))
    host = "127.0.0.1"
    try:
        server = ThreadingHTTPServer((host, port), make_handler(app))
    except OSError:
        server = ThreadingHTTPServer((host, 0), make_handler(app))
        port = server.server_address[1]
    print(f"LORA_MEMORY_READY port={port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
