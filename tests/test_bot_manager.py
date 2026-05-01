"""Tests for launcher/bot_manager.py — process lifecycle + status detection."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launcher import bot_manager
from launcher.bot_manager import BOT_SPECS, BotManager


def _write_mykey(tmp_path: Path, body: str = ""):
    (tmp_path / "mykey.py").write_text(body, encoding="utf-8")


def _patch_sdk(monkeypatch, available: dict[str, bool] | None = None):
    """Replace importlib.util.find_spec for SDK detection."""
    avail = available or {}

    def fake_find_spec(name):
        if name in avail:
            return object() if avail[name] else None
        # default: pretend installed unless override said otherwise
        return object()

    monkeypatch.setattr(bot_manager.importlib.util, "find_spec", fake_find_spec)


def test_status_unconfigured(tmp_path, monkeypatch):
    _write_mykey(tmp_path)  # empty
    _patch_sdk(monkeypatch)
    mgr = BotManager(str(tmp_path))
    st = mgr.status("feishu")
    assert st.configured is False
    assert "fs_app_id" in st.missing_fields
    assert "fs_app_secret" in st.missing_fields
    assert st.running is False


def test_status_configured(tmp_path, monkeypatch):
    _write_mykey(tmp_path, "fs_app_id = 'cli_x'\nfs_app_secret = 's'\n")
    _patch_sdk(monkeypatch)
    mgr = BotManager(str(tmp_path))
    st = mgr.status("feishu")
    assert st.configured is True
    assert st.missing_fields == []
    assert st.sdk_installed is True


def test_status_sdk_missing(tmp_path, monkeypatch):
    _write_mykey(tmp_path, "fs_app_id = 'x'\nfs_app_secret = 'y'\n")
    _patch_sdk(monkeypatch, available={"lark_oapi": False})
    mgr = BotManager(str(tmp_path))
    st = mgr.status("feishu")
    assert st.sdk_installed is False
    assert "lark_oapi" in st.missing_modules


def test_status_external_running_via_port(tmp_path, monkeypatch):
    _write_mykey(tmp_path, "qq_app_id = '1'\nqq_app_secret = '2'\n")
    _patch_sdk(monkeypatch)
    monkeypatch.setattr(bot_manager, "_port_in_use",
                        lambda p, host="127.0.0.1", timeout=0.2: p == BOT_SPECS["qq"].lock_port)
    mgr = BotManager(str(tmp_path))
    st = mgr.status("qq")
    assert st.running_external is True
    assert st.running_self is False
    assert st.running is True


def test_start_blocks_when_unconfigured(tmp_path, monkeypatch):
    _write_mykey(tmp_path)
    _patch_sdk(monkeypatch)
    mgr = BotManager(str(tmp_path))
    ok, msg = mgr.start("feishu")
    assert ok is False
    assert "缺少配置" in msg


def test_start_blocks_when_sdk_missing(tmp_path, monkeypatch):
    _write_mykey(tmp_path, "tg_bot_token = 'X'\n")
    _patch_sdk(monkeypatch, available={"telegram": False})
    mgr = BotManager(str(tmp_path))
    ok, msg = mgr.start("tg")
    assert ok is False
    assert "缺少依赖" in msg


class _FakePopen:
    def __init__(self, alive=True):
        self._alive = alive
        self.pid = 9999
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def kill(self):
        self.killed = True
        self._alive = False

    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_start_spawns_and_stop_terminates(tmp_path, monkeypatch):
    _write_mykey(tmp_path, "tg_bot_token = 'X'\n")
    (tmp_path / "frontends").mkdir(exist_ok=True)
    (tmp_path / "frontends" / "tgapp.py").write_text("# fake", encoding="utf-8")
    _patch_sdk(monkeypatch)
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakePopen(alive=True)

    monkeypatch.setattr(bot_manager.subprocess, "Popen", fake_popen)
    mgr = BotManager(str(tmp_path))
    ok, msg = mgr.start("tg")
    assert ok and "已启动" in msg
    assert captured["args"][1].endswith("tgapp.py")
    st = mgr.status("tg")
    assert st.running_self is True
    ok2, _ = mgr.stop("tg")
    assert ok2
    assert "tg" not in mgr._procs


def test_stop_when_not_running(tmp_path, monkeypatch):
    _write_mykey(tmp_path)
    mgr = BotManager(str(tmp_path))
    ok, msg = mgr.stop("feishu")
    assert ok and "未在运行" in msg


def test_configured_keys(tmp_path, monkeypatch):
    _write_mykey(
        tmp_path,
        "tg_bot_token = 'A'\nfs_app_id = 'X'\nfs_app_secret = 'Y'\n",
    )
    _patch_sdk(monkeypatch)
    mgr = BotManager(str(tmp_path))
    keys = set(mgr.configured_keys())
    assert "tg" in keys and "feishu" in keys
    assert "qq" not in keys
    assert "wechat" in keys  # wechat has no required mykey fields
