"""Tests for /api/bots/* endpoints in launcher.api_server.

Uses serve_threaded() like test_api_server_projects, with the BotManager
patched to exercise lifecycle paths without spawning real subprocesses.
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

from launcher import api_server, bot_manager


@pytest.fixture(scope="module")
def server_port(tmp_path_factory):
    """Module-scoped server backed by a tmp BotManager root.

    We only need the dirs `frontends/<bot>.py` exist for spawn tests; for the
    listing/log tests an empty tmp root is fine because mykey/SDK detection
    handles 'missing' gracefully.
    """
    tmp_dir = tmp_path_factory.mktemp("api_server_bots")
    (tmp_dir / "frontends").mkdir(exist_ok=True)
    api_server._bot_manager = bot_manager.BotManager(str(tmp_dir))

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


def _get(port: int, path: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(port: int, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = b"" if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_bots_list_includes_all_six(server_port):
    status, data = _get(server_port, "/api/bots")
    assert status == 200
    keys = {row["key"] for row in data["bots"]}
    assert keys == {"tg", "qq", "feishu", "wecom", "dingtalk", "wechat"}
    for row in data["bots"]:
        assert "configured" in row
        assert "running" in row
        assert "log_path" in row


def test_bot_start_unknown(server_port):
    status, data = _post(server_port, "/api/bots/unknown/start", {})
    assert status == 404
    assert data["error"] == "unknown_bot"


def test_bot_start_when_unconfigured_returns_409(server_port):
    # tmp BotManager has no mykey, so feishu is unconfigured -> 409 with reason
    status, data = _post(server_port, "/api/bots/feishu/start", {})
    assert status == 409
    assert "缺少" in data.get("message", "") or "configured" in data.get("message", "").lower()


def test_bot_stop_when_not_running(server_port):
    status, data = _post(server_port, "/api/bots/feishu/stop", {})
    assert status == 200
    assert "未在运行" in data.get("message", "") or "not" in data.get("message", "").lower()


def test_bot_log_no_file(server_port):
    status, data = _get(server_port, "/api/bots/feishu/log")
    assert status == 200
    assert data["exists"] is False
    assert data["lines"] == []


def test_bot_log_unknown(server_port):
    status, data = _get(server_port, "/api/bots/foobar/log")
    assert status == 404
    assert data["error"] == "unknown_bot"


def test_bot_log_with_file(server_port, tmp_path_factory):
    # Write a log file directly under the BotManager temp dir, then read it
    bm = api_server._bm()
    log_path = os.path.join(bm.temp_dir, "fsapp.log")
    os.makedirs(bm.temp_dir, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for i in range(50):
            f.write(f"line {i}\n")
    status, data = _get(server_port, "/api/bots/feishu/log")
    assert status == 200
    assert data["exists"] is True
    assert "line 0" in data["lines"][0]
    assert "line 49" in data["lines"][-1]
