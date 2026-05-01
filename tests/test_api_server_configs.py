"""Tests for /api/configs and /api/profiles endpoints in launcher.api_server."""
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
    """Module-scoped server backed by a tmp project root so configs / profiles
    don't pollute the real repo's mykey_local_override.py."""
    tmp_dir = tmp_path_factory.mktemp("api_server_configs")

    # Patch _project_root to point to our tmp dir for the lifetime of the module
    original_root = api_server._project_root
    api_server._project_root = lambda: str(tmp_dir)  # type: ignore[assignment]

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
    api_server._project_root = original_root  # type: ignore[assignment]


def _req(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _config(name: str, model: str = "gpt-test"):
    return {
        "kind": "native_oai",
        "name": name,
        "apikey": f"sk-{name}",
        "apibase": "https://x",
        "model": model,
    }


# ─── /api/configs ─────────────────────────────────────────────────────


def test_configs_save_and_list(server_port):
    status, data = _req(server_port, "PUT", "/api/configs", {"configs": [_config("alpha")]})
    assert status == 200
    names = [c["name"] for c in data["configs"]]
    assert "alpha" in names
    # apikey is masked on read paths
    assert all(c.get("apikey") in (None, "***") for c in data["configs"])


def test_configs_save_invalid_400(server_port):
    status, data = _req(server_port, "PUT", "/api/configs", {"configs": [{"kind": "native_oai", "name": "bad"}]})
    assert status == 400
    assert data["error"] == "invalid_config"


def test_configs_save_missing_field(server_port):
    status, data = _req(server_port, "PUT", "/api/configs", {})
    assert status == 400


# ─── /api/profiles ────────────────────────────────────────────────────


def test_profiles_initial_empty(server_port):
    # After reset (some prior test wiped configs.json), expect profiles empty
    status, data = _req(server_port, "GET", "/api/profiles")
    assert status == 200
    assert data["active"] in (None, "")  # no profile created yet for this server


def test_profile_upsert_create_and_set_active(server_port):
    _req(server_port, "PUT", "/api/configs", {"configs": [_config("alpha"), _config("beta")]})

    status, data = _req(
        server_port,
        "POST",
        "/api/profiles",
        {"name": "alpha-only", "members": ["alpha"]},
    )
    assert status == 200
    assert "alpha-only" in data["profiles"]
    assert data["profiles"]["alpha-only"] == ["alpha"]

    status, data = _req(
        server_port,
        "PUT",
        "/api/profiles/active",
        {"name": "alpha-only"},
    )
    assert status == 200
    assert data["active"] == "alpha-only"


def test_profile_upsert_missing_name(server_port):
    status, _ = _req(server_port, "POST", "/api/profiles", {"members": ["alpha"]})
    assert status == 400


def test_profile_set_active_unknown(server_port):
    status, _ = _req(server_port, "PUT", "/api/profiles/active", {"name": "nonexistent"})
    assert status == 404


def test_profile_set_active_to_null(server_port):
    status, data = _req(server_port, "PUT", "/api/profiles/active", {"name": None})
    assert status == 200
    assert data["active"] is None


def test_profile_rename(server_port):
    _req(server_port, "POST", "/api/profiles", {"name": "to-rename", "members": []})
    status, data = _req(server_port, "PATCH", "/api/profiles/to-rename", {"new_name": "renamed"})
    assert status == 200
    assert "renamed" in data["profiles"]
    assert "to-rename" not in data["profiles"]


def test_profile_rename_missing_new_name(server_port):
    status, _ = _req(server_port, "PATCH", "/api/profiles/whatever", {})
    assert status == 400


def test_profile_delete(server_port):
    _req(server_port, "POST", "/api/profiles", {"name": "doomed", "members": []})
    status, data = _req(server_port, "DELETE", "/api/profiles/doomed")
    assert status == 200
    assert "doomed" not in data["profiles"]


def test_profile_round_trip_persists_apikey(server_port):
    """Internal sanity: even though list_api_configs masks apikey on read,
    the saved file (mykey_local_override.py) must contain the real key for
    the agent to use."""
    _req(server_port, "PUT", "/api/configs", {"configs": [_config("gamma")]})
    override = os.path.join(api_server._project_root(), "mykey_local_override.py")
    assert os.path.isfile(override)
    text = open(override, encoding="utf-8").read()
    assert "sk-gamma" in text  # real key landed on disk
