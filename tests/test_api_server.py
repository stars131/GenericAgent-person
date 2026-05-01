"""Tests for launcher.api_server — stdlib http.server Phase 0 endpoints."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from launcher import api_server


@pytest.fixture(scope="module")
def live_server():
    # One shared server for the module to dodge Windows port-allocation flakiness
    # when many tests grab and release fresh ports in rapid succession.
    last_err: Exception | None = None
    for _ in range(5):
        try:
            port, _thread = api_server.serve_threaded()
            break
        except (OSError, PermissionError) as exc:
            last_err = exc
            continue
    else:
        raise RuntimeError(f"could not start api_server after 5 attempts: {last_err}")
    yield port


def _get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as resp:
        assert resp.status == 200
        return json.loads(resp.read())


def test_health(live_server: int) -> None:
    data = _get_json(live_server, "/api/health")
    assert data["status"] == "ok"
    assert data["uptime_s"] >= 0
    assert isinstance(data["pid"], int)


def test_version(live_server: int) -> None:
    data = _get_json(live_server, "/api/version")
    assert data["version"] == api_server.APP_VERSION
    assert data["api"] == api_server.API_VERSION
    assert "python" in data
    assert "platform" in data


def test_openapi_placeholder(live_server: int) -> None:
    data = _get_json(live_server, "/api/openapi.json")
    assert data["openapi"].startswith("3.")
    assert "/api/health" in data["paths"]


def test_unknown_route_404(live_server: int) -> None:
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"http://127.0.0.1:{live_server}/api/nope", timeout=2)
    assert excinfo.value.code == 404
    body = json.loads(excinfo.value.read())
    assert body["error"] == "not_found"
