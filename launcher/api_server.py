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


# ─── Bot credentials editor ───────────────────────────────────────────
#
# We surface ONLY a known whitelist of mykey fields that correspond to bot
# credentials. The whole mykey scan happens server-side; the GUI never sees
# unrelated keys (LLM apikeys, Sophub tokens, Langfuse, etc).

_BOT_CRED_FIELDS = {
    "tg": ["tg_bot_token", "tg_allowed_users"],
    "qq": ["qq_app_id", "qq_app_secret", "qq_allowed_users"],
    "feishu": ["fs_app_id", "fs_app_secret", "fs_allowed_users"],
    "wecom": ["wecom_bot_id", "wecom_secret", "wecom_allowed_users", "wecom_welcome_message"],
    "dingtalk": ["dingtalk_client_id", "dingtalk_client_secret", "dingtalk_allowed_users"],
}
_ALL_BOT_FIELDS = {f for fs in _BOT_CRED_FIELDS.values() for f in fs}


def _read_credentials() -> dict[str, Any]:
    """Read whitelisted bot credentials from mykey.py and mykey_local_override.py."""
    import runpy

    out: dict[str, Any] = {}
    for name in ("mykey.py", "mykey_local_override.py"):
        path = os.path.join(_project_root(), name)
        if not os.path.isfile(path):
            continue
        try:
            values = runpy.run_path(path)
        except Exception:
            continue
        for k, v in values.items():
            if k in _ALL_BOT_FIELDS:
                out[k] = v
    return out


def _route_credentials_get(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """GET /api/credentials → {fields: {bot:[..]}, values: {bot:{field:val}}}"""
    creds = _read_credentials()
    grouped: dict[str, dict[str, Any]] = {}
    for bot, fields in _BOT_CRED_FIELDS.items():
        grouped[bot] = {f: creds.get(f, "") for f in fields}
        # Mask secrets but leave list-valued fields intact for round-trip.
        for f in fields:
            if any(token in f for token in ("secret", "token")) and grouped[bot][f]:
                grouped[bot][f] = "***"
    return 200, {"fields": _BOT_CRED_FIELDS, "values": grouped}


def _route_credentials_put(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """PUT /api/credentials body: {<field>: <value>, ...}

    Only fields in the whitelist are written. `***` values are treated as
    "no change" so the UI can echo the masked GET payload back without
    nuking real values.
    """
    body = req["body"]
    if not isinstance(body, dict):
        return 400, {"error": "invalid_body"}
    incoming = {k: v for k, v in body.items() if k in _ALL_BOT_FIELDS}
    if not incoming:
        return 400, {"error": "no_known_fields"}

    existing = _read_credentials()
    merged = dict(existing)
    for k, v in incoming.items():
        if v == "***":
            continue  # preserve existing
        if isinstance(v, str) and not v.strip():
            merged.pop(k, None)
            continue
        merged[k] = v

    _write_credentials_to_override(merged)
    return _route_credentials_get(req)


def _write_credentials_to_override(creds: dict[str, Any]) -> None:
    """Append/replace bot credential lines in mykey_local_override.py.

    We preserve any unrelated lines (Qt launcher's auto-generated configs)
    by keeping their text and rewriting only the whitelisted assignments.
    """
    path = os.path.join(_project_root(), "mykey_local_override.py")
    existing_lines: list[str] = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # Strip any current assignments to whitelisted fields, keep the rest.
    keep: list[str] = []
    skip_blank_run = False
    import re as _re

    pattern = _re.compile(rf"^\s*({'|'.join(_re.escape(f) for f in _ALL_BOT_FIELDS)})\s*=")
    for line in existing_lines:
        if pattern.match(line):
            skip_blank_run = True
            continue
        if skip_blank_run and line.strip() == "":
            continue
        skip_blank_run = False
        keep.append(line)

    # Build new credential block
    block: list[str] = ["", "# bot credentials (managed by GUI /api/credentials)"]
    for k in sorted(creds):
        block.append(f"{k} = {creds[k]!r}")
    block.append("")

    new_text = "".join(keep).rstrip() + "\n" + "\n".join(block)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    try:
        import stat
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


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


def _route_activity_recent(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return the latest agent activity events (tool calls + turn boundaries)."""
    from launcher import activity_log as _alog

    raw_limit = req.get("query", {}).get("limit", "200")
    try:
        limit = max(1, min(2000, int(raw_limit)))
    except (TypeError, ValueError):
        limit = 200
    events = _alog.iter_recent(limit)
    return 200, {"events": events, "path": _alog.latest_path()}


def _route_skill_outcomes(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Aggregate turn_end events into per-skill outcome counts."""
    from launcher import activity_log as _alog

    summary = _alog.summarize_outcomes()
    skills = [{"name": name, **stats} for name, stats in summary.items()]
    skills.sort(key=lambda s: s["total"], reverse=True)
    return 200, {"skills": skills}


def _route_skills_list(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Return SOP files merged with their outcome counts (the skill catalogue)."""
    from launcher import skills as _skills

    return 200, {"skills": _skills.list_skills()}


def _route_token_usage(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Snapshot llmcore's running token-usage counters."""
    import llmcore as _llm

    return 200, _llm.get_token_usage()


def _route_token_usage_reset(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Zero the token-usage counters (GUI 'reset' button)."""
    import llmcore as _llm

    _llm.reset_token_usage()
    return 200, _llm.get_token_usage()


def _route_onboarding_status(_req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """First-run detection: does the user have a usable LLM config?"""
    from launcher import onboarding as _ob

    return 200, _ob.status()


def _route_onboarding_save(req: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Wizard submit — persist provider + key/base/model into ``.env``."""
    from launcher import onboarding as _ob

    body = req.get("body") or {}
    provider = str(body.get("provider", "") or "")
    apikey = str(body.get("apikey", "") or "")
    base_url = str(body.get("base_url", "") or "")
    model = str(body.get("model", "") or "")
    try:
        result = _ob.save_minimal(provider, apikey=apikey, base_url=base_url, model=model)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    return 200, result


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
    ("GET", "/api/credentials", _route_credentials_get),
    ("PUT", "/api/credentials", _route_credentials_put),
    ("GET", "/api/activity", _route_activity_recent),
    ("GET", "/api/skills/outcomes", _route_skill_outcomes),
    ("GET", "/api/skills", _route_skills_list),
    ("GET", "/api/token_usage", _route_token_usage),
    ("POST", "/api/token_usage/reset", _route_token_usage_reset),
    ("GET", "/api/onboarding/status", _route_onboarding_status),
    ("POST", "/api/onboarding/save", _route_onboarding_save),
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


# SSE streaming endpoints. Handlers receive the request handler instance
# and the matched path params, then write the response themselves —
# headers + body — until the client disconnects. Paths use the same
# `<id>` syntax as ROUTES.
SSE_ROUTES: list[tuple[str, Callable[["_Handler", dict[str, str]], None]]] = []


def _sse_route(pattern: str):
    def deco(fn: Callable[["_Handler", dict[str, str]], None]):
        SSE_ROUTES.append((pattern, fn))
        return fn
    return deco


def _send_sse_headers(handler: "_Handler") -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")  # nginx hint
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()


def _send_sse(handler: "_Handler", data: str, *, event: str | None = None) -> bool:
    """Write a single SSE frame. Returns False if the client has disconnected."""
    try:
        if event:
            handler.wfile.write(f"event: {event}\n".encode("utf-8"))
        for line in data.splitlines() or [""]:
            handler.wfile.write(f"data: {line}\n".encode("utf-8"))
        handler.wfile.write(b"\n")
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError, OSError):
        return False


def _tail_log_file(
    handler: "_Handler",
    path: str,
    *,
    initial_chars: int = 4000,
    poll_interval: float = 0.5,
    heartbeat: float = 25.0,
    max_seconds: float = 600.0,
) -> None:
    """Stream a log file as SSE: send the existing tail then follow new appends.

    Stops when the client disconnects, when max_seconds elapses, or when the
    file is rotated/deleted.
    """
    _send_sse_headers(handler)
    if not _send_sse(handler, json.dumps({"path": path, "exists": os.path.isfile(path)}), event="meta"):
        return

    if not os.path.isfile(path):
        # No file yet — keep heartbeating until it appears or the client leaves.
        deadline = time.monotonic() + max_seconds
        last_beat = time.monotonic()
        while time.monotonic() < deadline:
            if os.path.isfile(path):
                break
            now = time.monotonic()
            if now - last_beat > heartbeat:
                if not _send_sse(handler, "ping", event="heartbeat"):
                    return
                last_beat = now
            time.sleep(poll_interval)
        if not os.path.isfile(path):
            _send_sse(handler, json.dumps({"reason": "timeout"}), event="end")
            return
        if not _send_sse(handler, json.dumps({"path": path, "exists": True}), event="meta"):
            return

    try:
        f = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        _send_sse(handler, json.dumps({"error": str(exc)}), event="error")
        return

    try:
        # Seek to the start of the last `initial_chars` bytes.
        f.seek(0, 2)  # end
        size = f.tell()
        f.seek(max(0, size - initial_chars))
        # If we cut mid-line, drop the partial first line for tidiness.
        if size > initial_chars:
            f.readline()
        head = f.read()
        if head and not _send_sse(handler, head, event="append"):
            return

        deadline = time.monotonic() + max_seconds
        last_beat = time.monotonic()
        while time.monotonic() < deadline:
            chunk = f.read()
            if chunk:
                if not _send_sse(handler, chunk, event="append"):
                    return
                last_beat = time.monotonic()
                continue
            now = time.monotonic()
            if now - last_beat > heartbeat:
                if not _send_sse(handler, "ping", event="heartbeat"):
                    return
                last_beat = now
            # Detect rotation/truncation: if file shrunk, restart from end.
            try:
                cur_size = os.path.getsize(path)
            except OSError:
                _send_sse(handler, json.dumps({"reason": "deleted"}), event="end")
                return
            if cur_size < f.tell():
                f.seek(0)
            time.sleep(poll_interval)
        _send_sse(handler, json.dumps({"reason": "max_seconds"}), event="end")
    finally:
        try:
            f.close()
        except Exception:
            pass


@_sse_route("/api/projects/<id>/log/stream")
def _stream_project_log(handler: "_Handler", params: dict[str, str]) -> None:
    project = _pm().get(params["id"])
    if not project:
        handler._send_json({"error": "not_found"}, status=404)
        return
    log_path = project.get("log_path") or os.path.join(
        _project_root(), "temp", "project_logs", f"{project['id']}.log"
    )
    _tail_log_file(handler, log_path)


@_sse_route("/api/bots/<key>/log/stream")
def _stream_bot_log(handler: "_Handler", params: dict[str, str]) -> None:
    from launcher.bot_manager import BOT_SPECS

    key = params["key"]
    if key not in BOT_SPECS:
        handler._send_json({"error": "unknown_bot"}, status=404)
        return
    log_path = _bm().status(key).log_path
    _tail_log_file(handler, log_path)


@_sse_route("/api/activity/stream")
def _stream_activity(handler: "_Handler", params: dict[str, str]) -> None:
    """Tail the agent activity log (current day's JSONL)."""
    from launcher import activity_log as _alog

    _tail_log_file(handler, _alog.latest_path())


def _match_sse(path: str):
    for pattern, fn in SSE_ROUTES:
        params = _match_pattern(pattern, path)
        if params is not None:
            return fn, params
    return None, None


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
        parsed = urlparse(self.path)
        path = parsed.path
        handler, params = _match_route(method, path)
        if handler is None:
            self._send_json({"error": "not_found", "path": path, "method": method}, status=404)
            return
        body = self._read_body() if method in {"POST", "PUT", "PATCH", "DELETE"} else {}
        from urllib.parse import parse_qs
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        req = {"method": method, "path": path, "params": params, "body": body, "query": query}
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
        # SSE routes are matched first since they take ownership of the
        # response (they write headers + a long-lived body themselves).
        path = urlparse(self.path).path
        sse_handler, sse_params = _match_sse(path)
        if sse_handler is not None:
            try:
                sse_handler(self, sse_params or {})
            except Exception as exc:
                # Client most likely disconnected; safe to swallow.
                if os.environ.get("GA_API_DEBUG"):
                    print(f"[SSE] {path}: {exc}")
            return
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

