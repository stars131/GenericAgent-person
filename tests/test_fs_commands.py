"""Tests for frontends/fs_commands.py — slash command registry + handlers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontends import fs_commands


class _FakeCtx:
    def __init__(self, mutating_allowed=True):
        self.texts: list[str] = []
        self.files: list[str] = []
        self.send_text = self.texts.append
        self.send_file = self._send_file
        self.base_dir = str(PROJECT_ROOT)
        self.mutating_allowed = mutating_allowed
        self.extras = {}

    def _send_file(self, path):
        self.files.append(path)
        return True


# ─── parse / dispatch ───


def test_parse_basic():
    op, args = fs_commands.parse("/sop github project")
    assert op == "/sop"
    assert args == ["github", "project"]


def test_parse_quoted():
    op, args = fs_commands.parse('/run echo "hello world"')
    assert op == "/run"
    assert args == ["echo", "hello world"]


def test_parse_non_command():
    assert fs_commands.parse("hello") == ("", [])
    assert fs_commands.parse("") == ("", [])


def test_dispatch_unknown():
    ctx = _FakeCtx()
    assert fs_commands.dispatch("/notacmd", ctx) is False


def test_dispatch_handler_exception_caught(monkeypatch):
    ctx = _FakeCtx()
    monkeypatch.setitem(fs_commands.COMMANDS, "/boom", lambda args, c: (_ for _ in ()).throw(RuntimeError("x")))
    try:
        assert fs_commands.dispatch("/boom", ctx) is True
        assert any("内部错误" in t for t in ctx.texts)
    finally:
        fs_commands.COMMANDS.pop("/boom", None)


# ─── /sop ───


def test_sop_no_args(monkeypatch):
    ctx = _FakeCtx()
    fs_commands.dispatch("/sop", ctx)
    assert any("用法" in t for t in ctx.texts)


def test_sop_search_short_result(monkeypatch):
    monkeypatch.setattr(fs_commands, "sop_search", lambda q, top_k=5: f"results for {q}")
    ctx = _FakeCtx()
    fs_commands.dispatch("/sop github project", ctx)
    assert ctx.texts == ["results for github project"]


def test_sop_read_short_inline(monkeypatch):
    monkeypatch.setattr(fs_commands, "sop_read", lambda sid: "short content")
    ctx = _FakeCtx()
    fs_commands.dispatch("/sop read abc123", ctx)
    assert ctx.texts == ["short content"]
    assert ctx.files == []


def test_sop_read_long_sent_as_file(monkeypatch, tmp_path):
    big = "x" * 4000
    monkeypatch.setattr(fs_commands, "sop_read", lambda sid: big)
    monkeypatch.setattr(fs_commands, "SOP_OUT_DIR", str(tmp_path))
    ctx = _FakeCtx()
    fs_commands.dispatch("/sop read big_id", ctx)
    assert ctx.files and ctx.files[0].endswith("sop_big_id.md")
    assert any("已落盘" in t for t in ctx.texts)


def test_sop_stats(monkeypatch):
    monkeypatch.setattr(fs_commands, "sop_stats", lambda: "Sophub: 999 SOPs")
    ctx = _FakeCtx()
    fs_commands.dispatch("/sop stats", ctx)
    assert ctx.texts == ["Sophub: 999 SOPs"]


# ─── /screenshot ───


def test_screenshot_invalid_arg():
    ctx = _FakeCtx()
    fs_commands.dispatch("/screenshot abc", ctx)
    assert any("用法" in t for t in ctx.texts)


def test_screenshot_dependency_missing(monkeypatch):
    monkeypatch.setattr(fs_commands, "_take_screenshot", lambda path, monitor=0: (None, "缺少截图依赖"))
    ctx = _FakeCtx()
    fs_commands.dispatch("/screenshot", ctx)
    assert any("截图失败" in t and "缺少截图依赖" in t for t in ctx.texts)
    assert ctx.files == []


def test_screenshot_success(monkeypatch, tmp_path):
    monkeypatch.setattr(fs_commands, "SCREENSHOT_DIR", str(tmp_path))

    def fake(path, monitor=0):
        Path(path).write_bytes(b"PNGdata")
        return path, None

    monkeypatch.setattr(fs_commands, "_take_screenshot", fake)
    ctx = _FakeCtx()
    fs_commands.dispatch("/screenshot 1", ctx)
    assert len(ctx.files) == 1
    assert ctx.files[0].endswith(".png")


# ─── /run ───


def test_run_no_args():
    ctx = _FakeCtx()
    fs_commands.dispatch("/run", ctx)
    assert any("用法" in t for t in ctx.texts)


def test_run_blocked_when_public():
    ctx = _FakeCtx(mutating_allowed=False)
    fs_commands.dispatch("/run echo hi", ctx)
    assert any("禁用" in t for t in ctx.texts)


def test_run_executes_simple_cmd():
    ctx = _FakeCtx()
    cmd = "echo hi" if os.name != "nt" else "cmd /c echo hi"
    fs_commands.dispatch(f"/run {cmd}", ctx)
    assert any("hi" in t and "exit=0" in t for t in ctx.texts)


# ─── /clip ───


def test_clip_get(monkeypatch):
    monkeypatch.setattr(fs_commands, "_clip_get", lambda: ("hello", None))
    ctx = _FakeCtx()
    fs_commands.dispatch("/clip", ctx)
    assert any("hello" in t for t in ctx.texts)


def test_clip_get_error(monkeypatch):
    monkeypatch.setattr(fs_commands, "_clip_get", lambda: (None, "no display"))
    ctx = _FakeCtx()
    fs_commands.dispatch("/clip", ctx)
    assert any("失败" in t for t in ctx.texts)


def test_clip_set_blocked_public(monkeypatch):
    ctx = _FakeCtx(mutating_allowed=False)
    fs_commands.dispatch("/clip foo bar", ctx)
    assert any("禁用" in t for t in ctx.texts)


def test_clip_set_ok(monkeypatch):
    monkeypatch.setattr(fs_commands, "_clip_set", lambda t: (True, None))
    ctx = _FakeCtx()
    fs_commands.dispatch("/clip secret", ctx)
    assert any("已写入剪贴板" in t for t in ctx.texts)


# ─── /open ───


def test_open_no_args():
    ctx = _FakeCtx()
    fs_commands.dispatch("/open", ctx)
    assert any("用法" in t for t in ctx.texts)


def test_open_blocked_public():
    ctx = _FakeCtx(mutating_allowed=False)
    fs_commands.dispatch("/open https://example.com", ctx)
    assert any("禁用" in t for t in ctx.texts)


def test_open_dispatches(monkeypatch):
    captured = {}

    def fake(target):
        captured["target"] = target
        return True, None

    monkeypatch.setattr(fs_commands, "_open_target", fake)
    ctx = _FakeCtx()
    fs_commands.dispatch("/open https://example.com", ctx)
    assert captured["target"] == "https://example.com"
    assert any("已请求打开" in t for t in ctx.texts)


# ─── help_text ───


def test_help_text_contains_all_commands():
    ht = fs_commands.help_text()
    for name in ("/sop", "/screenshot", "/run", "/clip", "/open"):
        assert name in ht
