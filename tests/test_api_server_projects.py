"""End-to-end tests for the Phase 1 endpoints in launcher.api_server.

We start the server in-process (serve_threaded) and drive it with
urllib so we exercise the full HTTP plumbing including method dispatch,
body parsing, and CORS headers.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from launcher import api_server


@pytest.fixture(scope="module")
def server_port(tmp_path_factory):
    """Module-scoped server. Reuses one HTTP listener across tests to avoid
    Windows port-allocation flakiness."""
    # Redirect ProjectManager to a tmp projects.json by monkeypatching the
    # singleton accessor before any test creates a project.
    tmp_dir = tmp_path_factory.mktemp("api_server_projects")
    from launcher.project_manager import ProjectManager
    pm = ProjectManager(str(tmp_dir))
    api_server._project_manager = pm

    port = None
    last_err: Exception | None = None
    for _ in range(5):
        try:
            port, _t = api_server.serve_threaded()
            break
        except (OSError, PermissionError) as exc:
            last_err = exc
    if port is None:
        raise RuntimeError(f"could not start server: {last_err}")
    yield port
    # leave thread; daemon dies with process


def _get(port: int, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _req(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# ─── projects ─────────────────────────────────────────────────────────


def test_projects_empty(server_port):
    status, data = _get(server_port, "/api/projects")
    assert status == 200
    assert data["projects"] == []
    assert data["active_id"] is None


def test_create_project(server_port):
    status, data = _req(server_port, "POST", "/api/projects", {"name": "demo"})
    assert status == 201
    assert data["project"]["name"] == "demo"
    assert data["project"]["llm_config_name"] == ""
    pid = data["project"]["id"]

    status, listing = _get(server_port, "/api/projects")
    assert status == 200
    assert any(p["id"] == pid for p in listing["projects"])


def test_get_project_404(server_port):
    status, data = _get(server_port, "/api/projects/nope")
    assert status == 404
    assert data["error"] == "not_found"


def test_set_llm_by_name(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "x"})
    pid = created["project"]["id"]
    status, data = _req(server_port, "PUT", f"/api/projects/{pid}/llm", {"config_name": "gpt-native"})
    assert status == 200
    assert data["project"]["llm_config_name"] == "gpt-native"


def test_set_llm_no_change(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "y"})
    pid = created["project"]["id"]
    status, data = _req(server_port, "PUT", f"/api/projects/{pid}/llm", {"llm_no": 3})
    assert status == 200
    assert data["project"]["llm_no"] == 3


def test_set_llm_missing_field(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "z"})
    pid = created["project"]["id"]
    status, _ = _req(server_port, "PUT", f"/api/projects/{pid}/llm", {})
    assert status == 400


def test_set_llm_unknown_project(server_port):
    status, _ = _req(server_port, "PUT", "/api/projects/nope/llm", {"config_name": "x"})
    assert status == 404


def test_rename_project(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "old"})
    pid = created["project"]["id"]
    status, data = _req(server_port, "PATCH", f"/api/projects/{pid}", {"name": "new"})
    assert status == 200
    assert data["project"]["name"] == "new"


def test_pin_project(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "p"})
    pid = created["project"]["id"]
    status, data = _req(server_port, "POST", f"/api/projects/{pid}/pin", {"pinned": True})
    assert status == 200
    assert data["project"]["pinned"] is True


def test_activate_project(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "act"})
    pid = created["project"]["id"]
    status, data = _req(server_port, "POST", f"/api/projects/{pid}/activate", {})
    assert status == 200
    assert data["project"]["id"] == pid


def test_delete_project(server_port):
    _, created = _req(server_port, "POST", "/api/projects", {"name": "doomed"})
    pid = created["project"]["id"]
    status, data = _req(server_port, "DELETE", f"/api/projects/{pid}")
    assert status == 200
    assert data["deleted"] == pid
    status, _ = _get(server_port, f"/api/projects/{pid}")
    assert status == 404


# ─── configs / profiles ───────────────────────────────────────────────


def test_configs_list_empty(server_port, monkeypatch):
    # In our tmp_path PM, mykey scaffolding may or may not exist; configs come
    # from launcher_api_configs.json which doesn't exist by default → empty.
    status, data = _get(server_port, "/api/configs")
    assert status == 200
    assert "configs" in data
    assert isinstance(data["configs"], list)


def test_profiles_default(server_port):
    status, data = _get(server_port, "/api/profiles")
    assert status == 200
    assert data["active"] is None
    assert data["profiles"] == {}


# ─── method dispatch ──────────────────────────────────────────────────


def test_options_preflight(server_port):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server_port}/api/projects",
        method="OPTIONS",
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        assert r.status == 204
        assert r.headers["Access-Control-Allow-Methods"]
