"""HTTP API server for the GenericAgent GUI (Tauri webview).

Phase 0 ships /api/health, /api/version, /api/openapi.json.

Phase 1 adds business endpoints backed by ProjectManager / api_config:

  GET    /api/projects                     -> list projects (running flag included)
  POST   /api/projects                     -> create new project; body: {name, options?}
  GET    /api/projects/<id>                -> single project detail
  DELETE /api/projects/<id>                -> stop + remove
  POST   /api/projects/<id>/start          -> start the streamlit subprocess
  POST   /api/projects/<id>/stop           -> stop the subprocess
  POST   /api/projects/<id>/activate       -> mark as last-active
  POST   /api/projects/<id>/pin            -> body: {pinned: bool}
  PATCH  /api/projects/<id>                -> body: {name?: str}  (rename)
  PUT    /api/projects/<id>/llm            -> body: {config_name?: str, llm_no?: int}
                                              ADR-0006 per-session API selection.

  GET    /api/configs                      -> list api_config entries (apikey masked)
  GET    /api/profiles                     -> {active, profiles: {name: [config_names]}}

Run standalone:

    python -m launcher.api_server --port 18800
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
from urllib.parse import urlparse

API_VERSION = "v1"
APP_VERSION = "0.1.0"
READY_MARKER = "__GA_READY__"

_started_at = time.monotonic()
_project_manager = None  # lazy ProjectManager instance
_bot_manager = None  # lazy BotManager instance


# ─── Lazy backend wiring ───────────────────────────────────────────────


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pm():
    """Singleton ProjectManager. Imported lazily so health-only callers
    don't pay the import cost."""
    global _project_manager
    if _project_manager is None:
        from launcher.project_manager import ProjectManager
        _project_manager = ProjectManager(_project_root())
    return _project_manager


def _bm():
    """Singleton BotManager."""
    global _bot_manager
    if _bot_manager is None:
        from launcher.bot_manager import BotManager
        _bot_manager = BotManager(_project_root())
    return _bot_manager


# ─── Route handlers ────────────────────────────────────────────────────


def _route_health(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return 200, {
        "status": "ok",
        "uptime_s": round(time.monotonic() - _started_at, 3),
        "pid": os.getpid(),
    }


def _route_version(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return 200, {
        "version": APP_VERSION,
        "api": API_VERSION,
        "python": platform.python_version(),
        "platform": sys.platform,
    }


def _route_openapi(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return 200, {
        "openapi": "3.1.0",
        "info": {
            "title": "GenericAgent API",
            "version": APP_VERSION,
            "description": "Phase 1: projects, configs, profiles. See module docstring.",
        },
        "paths": {p: {} for p in _all_paths()},
    }


def _route_projects_list(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = _pm().list()
    return 200, {"projects": data["projects"], "active_id": data["active_id"]}


def _route_projects_create(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    body = req["body"]
    name = str(body.get("name") or "").strip() or "新对话"
    options = body.get("options") if isinstance(body.get("options"), dict) else None
    project = _pm().create(name, auto_start=False, options=options)
    return 201, {"project": project}


def _route_project_get(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    project = _pm().get(req["params"]["id"])
    if not project:
        return 404, {"error": "not_found", "id": req["params"]["id"]}
    return 200, {"project": project}


def _route_project_delete(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pid = req["params"]["id"]
    if not _pm().get(pid):
        return 404, {"error": "not_found", "id": pid}
    _pm().delete(pid)
    return 200, {"deleted": pid}


def _route_project_start(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pid = req["params"]["id"]
    if not _pm().get(pid):
        return 404, {"error": "not_found", "id": pid}
    try:
        _pm().start(pid)
    except Exception as exc:
        return 500, {"error": "start_failed", "detail": str(exc)}
    return 200, {"project": _pm().get(pid)}


def _route_project_stop(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pid = req["params"]["id"]
    if not _pm().get(pid):
        return 404, {"error": "not_found", "id": pid}
    _pm().stop(pid)
    return 200, {"project": _pm().get(pid)}


def _route_project_activate(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pid = req["params"]["id"]
    if not _pm().set_active(pid):
        return 404, {"error": "not_found", "id": pid}
    return 200, {"project": _pm().get(pid)}


def _route_project_pin(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pid = req["params"]["id"]
    pinned = bool(req["body"].get("pinned", True))
    if not _pm().pin(pid, pinned):
        return 404, {"error": "not_found", "id": pid}
    return 200, {"project": _pm().get(pid)}


def _route_project_patch(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    pid = req["params"]["id"]
    body = req["body"]
    if "name" in body:
        ok = _pm().rename(pid, str(body["name"] or ""))
        if not ok:
            return 400, {"error": "rename_failed"}
    return 200, {"project": _pm().get(pid)}


def _route_project_set_llm(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """ADR-0006: PUT /api/projects/<id>/llm with {config_name?, llm_no?}."""
    pid = req["params"]["id"]
    body = req["body"]
    config_name = body.get("config_name")
    llm_no = body.get("llm_no")
    if config_name is None and llm_no is None:
        return 400, {"error": "missing_field", "expected": "config_name or llm_no"}
    updated = _pm().set_llm(pid, config_name=config_name, llm_no=llm_no)
    if updated is None:
        return 404, {"error": "not_found", "id": pid}
    return 200, {"project": _pm().get(pid)}


def _route_configs_list(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from launcher.api_config import list_api_configs

    return 200, {"configs": list_api_configs(_project_root())}


def _route_configs_save(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """PUT /api/configs — replace the whole list (mirrors Qt launcher save)."""
    from launcher.api_config import list_api_configs, save_api_configs

    body = req["body"]
    incoming = body.get("configs")
    if not isinstance(incoming, list):
        return 400, {"error": "missing_field", "expected": "configs: [..]"}
    try:
        save_api_configs(_project_root(), incoming)
    except ValueError as exc:
        return 400, {"error": "invalid_config", "detail": str(exc)}
    # Return through list_api_configs so apikey is masked, matching GET path.
    return 200, {"configs": list_api_configs(_project_root())}


def _route_profiles_get(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from launcher.api_config import load_profiles

    state = load_profiles(_project_root())
    return 200, {"active": state.get("active"), "profiles": state.get("profiles", {})}


def _route_profiles_set_active(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """PUT /api/profiles/active body: {name: str|null}"""
    from launcher.api_config import load_profiles, set_active_profile

    name = req["body"].get("name")
    if name is not None and not isinstance(name, str):
        return 400, {"error": "invalid_name"}
    try:
        set_active_profile(_project_root(), name)
    except ValueError as exc:
        return 404, {"error": "profile_not_found", "detail": str(exc)}
    return 200, load_profiles(_project_root())


def _route_profiles_upsert(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """POST /api/profiles body: {name, members}"""
    from launcher.api_config import load_profiles, upsert_profile

    body = req["body"]
    name = str(body.get("name") or "").strip()
    members = body.get("members") or []
    if not name:
        return 400, {"error": "missing_name"}
    if not isinstance(members, list):
        return 400, {"error": "invalid_members"}
    try:
        upsert_profile(_project_root(), name, [str(m) for m in members])
    except ValueError as exc:
        return 400, {"error": "invalid", "detail": str(exc)}
    return 200, load_profiles(_project_root())


def _route_profile_rename(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """PATCH /api/profiles/<name> body: {new_name}"""
    from launcher.api_config import load_profiles, rename_profile

    old_name = req["params"]["name"]
    new_name = str(req["body"].get("new_name") or "").strip()
    if not new_name:
        return 400, {"error": "missing_new_name"}
    try:
        rename_profile(_project_root(), old_name, new_name)
    except ValueError as exc:
        return 400, {"error": "rename_failed", "detail": str(exc)}
    return 200, load_profiles(_project_root())


def _route_profile_delete(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """DELETE /api/profiles/<name>"""
    from launcher.api_config import delete_profile, load_profiles

    name = req["params"]["name"]
    delete_profile(_project_root(), name)
    return 200, load_profiles(_project_root())


def _route_settings_get(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """GET /api/settings — read launcher_options.json normalised."""
    from launcher.launch_config import load_options

    return 200, {"settings": load_options(_project_root())}


def _route_settings_put(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """PUT /api/settings — overwrite launcher_options.json with normalised body."""
    from launcher.launch_config import load_options, save_options

    body = req["body"]
    if not isinstance(body, dict):
        return 400, {"error": "invalid_body"}
    # Merge over existing so the UI can send partial updates.
    merged = {**load_options(_project_root()), **body}
    saved = save_options(_project_root(), merged)
    return 200, {"settings": saved}


def _route_bots_list(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from launcher.bot_manager import BOT_SPECS

    statuses = _bm().status_all()
    rows = []
    for key, spec in BOT_SPECS.items():
        st = statuses[key]
        rows.append({
            "key": key,
            "display_name": spec.display_name,
            "script": spec.script,
            "configured": st.configured,
            "missing_fields": st.missing_fields,
            "sdk_installed": st.sdk_installed,
            "missing_modules": st.missing_modules,
            "running_self": st.running_self,
            "running_external": st.running_external,
            "running": st.running,
            "log_path": st.log_path,
        })
    return 200, {"bots": rows}


def _route_bot_start(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from launcher.bot_manager import BOT_SPECS

    key = req["params"]["key"]
    if key not in BOT_SPECS:
        return 404, {"error": "unknown_bot", "key": key}
    ok, message = _bm().start(key)
    if not ok:
        return 409, {"error": "start_failed", "key": key, "message": message}
    return 200, {"key": key, "message": message}


def _route_bot_stop(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from launcher.bot_manager import BOT_SPECS

    key = req["params"]["key"]
    if key not in BOT_SPECS:
        return 404, {"error": "unknown_bot", "key": key}
    ok, message = _bm().stop(key)
    if not ok:
        return 500, {"error": "stop_failed", "key": key, "message": message}
    return 200, {"key": key, "message": message}


def _route_bot_log(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return the last N lines of a bot's log file. Useful for debugging from
    the UI without the user opening the file system."""
    from launcher.bot_manager import BOT_SPECS

    key = req["params"]["key"]
    if key not in BOT_SPECS:
        return 404, {"error": "unknown_bot", "key": key}
    st = _bm().status(key)
    path = st.log_path
    if not path or not os.path.isfile(path):
        return 200, {"key": key, "path": path, "lines": [], "exists": False}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as exc:
        return 500, {"error": "read_failed", "detail": str(exc)}
    # Cap the response so we don't send 50 MB of bot chatter to a webview
    tail = text[-16000:] if len(text) > 16000 else text
    lines = tail.splitlines()[-200:]
    return 200, {"key": key, "path": path, "lines": lines, "exists": True}


# Path patterns. `<id>` is the projects' generated id.
ROUTES: list[tuple[str, str, Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]]] = [
    ("GET", "/api/health", _route_health),
    ("GET", "/api/version", _route_version),
    ("GET", "/api/openapi.json", _route_openapi),
    ("GET", "/api/projects", _route_projects_list),
    ("POST", "/api/projects", _route_projects_create),
    ("GET", "/api/projects/<id>", _route_project_get),
    ("DELETE", "/api/projects/<id>", _route_project_delete),
    ("POST", "/api/projects/<id>/start", _route_project_start),
    ("POST", "/api/projects/<id>/stop", _route_project_stop),
    ("POST", "/api/projects/<id>/activate", _route_project_activate),
    ("POST", "/api/projects/<id>/pin", _route_project_pin),
    ("PATCH", "/api/projects/<id>", _route_project_patch),
    ("PUT", "/api/projects/<id>/llm", _route_project_set_llm),
    ("GET", "/api/configs", _route_configs_list),
    ("PUT", "/api/configs", _route_configs_save),
    ("GET", "/api/profiles", _route_profiles_get),
    ("PUT", "/api/profiles/active", _route_profiles_set_active),
    ("POST", "/api/profiles", _route_profiles_upsert),
    ("PATCH", "/api/profiles/<name>", _route_profile_rename),
    ("DELETE", "/api/profiles/<name>", _route_profile_delete),
    ("GET", "/api/bots", _route_bots_list),
    ("POST", "/api/bots/<key>/start", _route_bot_start),
    ("POST", "/api/bots/<key>/stop", _route_bot_stop),
    ("GET", "/api/bots/<key>/log", _route_bot_log),
    ("GET", "/api/settings", _route_settings_get),
    ("PUT", "/api/settings", _route_settings_put),
]


def _all_paths() -> list[str]:
    return [p for _m, p, _h in ROUTES]


def _match_route(method: str, path: str):
    """Returns (handler, params_dict) or (None, None)."""
    for m, pattern, handler in ROUTES:
        if m != method:
            continue
        params = _match_pattern(pattern, path)
        if params is not None:
            return handler, params
    return None, None


def _match_pattern(pattern: str, path: str):
    p_parts = pattern.split("/")
    a_parts = path.split("/")
    if len(p_parts) != len(a_parts):
        return None
    out: dict[str, str] = {}
    for pp, ap in zip(p_parts, a_parts):
        if pp.startswith("<") and pp.endswith(">"):
            out[pp[1:-1]] = ap
        elif pp != ap:
            return None
    return out


# ─── HTTP plumbing ─────────────────────────────────────────────────────


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "GenericAgentAPI/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if os.environ.get("GA_API_DEBUG"):
            super().log_message(format, *args)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        handler, params = _match_route(method, path)
        if handler is None:
            self._send_json({"error": "not_found", "path": path, "method": method}, status=404)
            return
        body = self._read_body() if method in {"POST", "PUT", "PATCH", "DELETE"} else {}
        req = {"method": method, "path": path, "params": params, "body": body}
        try:
            status, payload = handler(req)
        except Exception as exc:
            self._send_json(
                {"error": "internal", "type": type(exc).__name__, "detail": str(exc)},
                status=500,
            )
            return
        self._send_json(payload, status=status)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")


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
    time.sleep(0.02)
    return port, thread


def reset_state_for_tests() -> None:
    """Reset module-level singletons. Tests use this between cases."""
    global _project_manager, _bot_manager, _started_at
    _project_manager = None
    _bot_manager = None
    _started_at = time.monotonic()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GenericAgent GUI API server")
    parser.add_argument("--port", type=int, default=None, help="TCP port (default: pick free)")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    serve(port=args.port, host=args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

