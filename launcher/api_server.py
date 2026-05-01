"""HTTP API server for the GenericAgent GUI (Tauri webview).

Phase 0 exposes only the bare minimum needed to prove the IPC pipeline:

  GET /api/health    -> {"status":"ok","uptime_s":..,"pid":..}
  GET /api/version   -> {"version":..,"api":..,"python":..,"platform":..}
  GET /api/openapi.json -> placeholder; future phases publish a real OpenAPI doc

Implemented on stdlib `http.server` (matches `launcher/shell_server.py`); no
extra dependency. Phase 1 modules will register more routes by extending the
`ROUTES` table at the bottom of this file.

Run standalone:

    python -m launcher.api_server --port 18800

The Tauri shell spawns this with `--port <free>` and waits for a line
starting with `__GA_READY__` on stdout before opening the webview.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import socket
import socketserver
import sys
import threading
import time
from typing import Any, Callable

API_VERSION = "v1"
APP_VERSION = "0.1.0"
READY_MARKER = "__GA_READY__"

_started_at = time.monotonic()


# ─── Route handlers ────────────────────────────────────────────────────


def _route_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "uptime_s": round(time.monotonic() - _started_at, 3),
        "pid": os.getpid(),
    }


def _route_version() -> dict[str, Any]:
    return {
        "version": APP_VERSION,
        "api": API_VERSION,
        "python": platform.python_version(),
        "platform": sys.platform,
    }


def _route_openapi() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "GenericAgent API",
            "version": APP_VERSION,
            "description": "Phase 0 placeholder — only /api/health and /api/version are live.",
        },
        "paths": {
            "/api/health": {"get": {"summary": "Liveness probe"}},
            "/api/version": {"get": {"summary": "Build metadata"}},
        },
    }


# Method -> { path -> handler returning JSON-serialisable value }
ROUTES: dict[str, dict[str, Callable[[], Any]]] = {
    "GET": {
        "/api/health": _route_health,
        "/api/version": _route_version,
        "/api/openapi.json": _route_openapi,
    },
}


# ─── HTTP plumbing ─────────────────────────────────────────────────────


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "GenericAgentAPI/0.1"

    # Suppress per-request logging unless explicitly debugging
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if os.environ.get("GA_API_DEBUG"):
            super().log_message(format, *args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Permissive CORS for local Tauri webview / Vite dev origin
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        handlers = ROUTES.get(method, {})
        path = self.path.split("?", 1)[0]
        handler = handlers.get(path)
        if handler is None:
            self._send_json({"error": "not_found", "path": path}, status=404)
            return
        try:
            payload = handler()
        except Exception as exc:  # surface unexpected handler errors
            self._send_json(
                {"error": "internal", "type": type(exc).__name__, "detail": str(exc)},
                status=500,
            )
            return
        self._send_json(payload)

    def do_GET(self) -> None:
        self._dispatch("GET")


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _make_server(host: str, port: int) -> _ThreadingServer:
    return _ThreadingServer((host, port), _Handler)


def serve(port: int | None = None, host: str = "127.0.0.1") -> None:
    """Run the API server (blocking). Prints `__GA_READY__ port=...` once listening."""
    if port is None:
        port = _free_port()
    httpd = _make_server(host, port)
    print(f"{READY_MARKER} port={port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def serve_threaded(port: int | None = None) -> tuple[int, threading.Thread]:
    """Run the server in a daemon thread; returns (port, thread). For tests."""
    if port is None:
        port = _free_port()

    httpd = _make_server("127.0.0.1", port)

    def _run() -> None:
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    # Wait briefly for the listening socket to actually accept; the typical
    # ready window is sub-millisecond on localhost.
    time.sleep(0.02)
    return port, thread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GenericAgent GUI API server")
    parser.add_argument("--port", type=int, default=None, help="TCP port (default: pick free)")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    serve(port=args.port, host=args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
