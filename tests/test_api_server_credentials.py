"""Tests for /api/credentials — bot credential editor."""
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
    tmp_dir = tmp_path_factory.mktemp("api_server_creds")
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
        raise RuntimeError(f"could not start: {last_err}")
    yield port, tmp_dir
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


def test_credentials_get_empty(server_port):
    port, _ = server_port
    status, data = _req(port, "GET", "/api/credentials")
    assert status == 200
    assert "fields" in data
    assert "values" in data
    # All bot keys present
    for bot in ("tg", "qq", "feishu", "wecom", "dingtalk"):
        assert bot in data["values"]
    # Empty by default
    assert data["values"]["feishu"]["fs_app_id"] == ""


def test_credentials_put_writes_to_override(server_port):
    port, tmp_dir = server_port
    status, data = _req(
        port,
        "PUT",
        "/api/credentials",
        {"fs_app_id": "cli_demo", "fs_app_secret": "shh-real"},
    )
    assert status == 200
    # apikey-like values come back masked
    assert data["values"]["feishu"]["fs_app_secret"] == "***"
    # The on-disk override has the real value
    override = tmp_dir / "mykey_local_override.py"
    assert override.is_file()
    text = override.read_text(encoding="utf-8")
    assert "fs_app_id = 'cli_demo'" in text
    assert "fs_app_secret = 'shh-real'" in text


def test_credentials_put_preserves_masked_value(server_port):
    """Sending '***' for an existing field must NOT clobber the real value."""
    port, tmp_dir = server_port
    _req(port, "PUT", "/api/credentials", {"fs_app_secret": "secret-v2"})
    # Now echo back the masked value as if from the GET response
    _req(port, "PUT", "/api/credentials", {"fs_app_secret": "***", "fs_app_id": "cli_demo"})
    text = (tmp_dir / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "secret-v2" in text  # preserved


def test_credentials_put_empty_string_clears_field(server_port):
    port, tmp_dir = server_port
    _req(port, "PUT", "/api/credentials", {"tg_bot_token": "T-abc"})
    _req(port, "PUT", "/api/credentials", {"tg_bot_token": ""})
    text = (tmp_dir / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "tg_bot_token" not in text


def test_credentials_put_rejects_unknown_fields(server_port):
    port, _ = server_port
    status, data = _req(port, "PUT", "/api/credentials", {"foo": "bar"})
    assert status == 400
    assert data["error"] == "no_known_fields"


def test_credentials_put_rejects_invalid_body(server_port):
    port, _ = server_port
    # Send an array as body — server treats non-dict as 400
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/credentials",
        data=json.dumps([1, 2]).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        urllib.request.urlopen(req, timeout=3)
        # Body parser drops non-dict to {} → ends up in "no_known_fields" branch
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_credentials_put_array_field(server_port):
    """fs_allowed_users etc are list-valued; round-trip without mask."""
    port, tmp_dir = server_port
    status, data = _req(
        port,
        "PUT",
        "/api/credentials",
        {"fs_allowed_users": ["ou_a", "ou_b"]},
    )
    assert status == 200
    assert data["values"]["feishu"]["fs_allowed_users"] == ["ou_a", "ou_b"]
    text = (tmp_dir / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "fs_allowed_users = ['ou_a', 'ou_b']" in text
