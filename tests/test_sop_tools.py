"""Tests for tools/sop_tools.py — wraps memory.skill_search engine."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import sop_tools


class _FakeSkill:
    def __init__(self, key, name, summary):
        self.key = key
        self.name = name
        self.one_line_summary = summary
        self.description = summary


class _FakeResult:
    def __init__(self, key, name, summary, quality=4.5, final=0.9):
        self.skill = _FakeSkill(key, name, summary)
        self.quality = quality
        self.final_score = final


class _FakeSop:
    def __init__(self, sop_id, title, content, author=""):
        self.id = sop_id
        self.title = title
        self.content = content
        self.preview = ""
        self.author = author


class _FakeError(Exception):
    pass


def _patch_engine(monkeypatch, search_fn=None, read_fn=None, stats_fn=None, error_cls=None):
    err_cls = error_cls or _FakeError
    fake = types.SimpleNamespace(
        SkillSearchError=err_cls,
        search=search_fn or (lambda q, top_k=5: []),
        read_sop=read_fn or (lambda sid: _FakeSop(sid, "x", "")),
        get_stats=stats_fn or (lambda: {"total": 0, "api_url": "https://x"}),
    )
    monkeypatch.setattr(sop_tools, "_import_engine",
                        lambda: (fake.SkillSearchError, fake.search, fake.read_sop, fake.get_stats))


def test_sop_search_formats_results(monkeypatch):
    results = [
        _FakeResult("aaa1", "Create GitHub Repo", "One-click GH repo bootstrap"),
        _FakeResult("bbb2", "GitHub Pages Deploy", "Push static site to gh-pages"),
    ]
    _patch_engine(monkeypatch, search_fn=lambda q, top_k=5: results[:top_k])
    out = sop_tools.sop_search("github", top_k=5)
    assert "Found 2 SOPs" in out
    assert "aaa1" in out and "bbb2" in out
    assert "Create GitHub Repo" in out
    assert "sop_read" in out


def test_sop_search_empty_query():
    assert sop_tools.sop_search("").startswith("[sop_search error]")


def test_sop_search_no_results(monkeypatch):
    _patch_engine(monkeypatch, search_fn=lambda q, top_k=5: [])
    assert "No SOPs found" in sop_tools.sop_search("nonexistent thing")


def test_sop_search_engine_error(monkeypatch):
    def raise_err(q, top_k=5):
        raise _FakeError("boom")
    _patch_engine(monkeypatch, search_fn=raise_err, error_cls=_FakeError)
    out = sop_tools.sop_search("any")
    assert out.startswith("[sop_search error]") and "boom" in out


def test_sop_search_unexpected_exception(monkeypatch):
    def raise_other(q, top_k=5):
        raise ValueError("oops")
    _patch_engine(monkeypatch, search_fn=raise_other)
    out = sop_tools.sop_search("any")
    assert "[sop_search error]" in out and "ValueError" in out


def test_sop_read_returns_full(monkeypatch):
    sop = _FakeSop("xyz9", "Demo SOP", "step1\nstep2", author="alice")
    _patch_engine(monkeypatch, read_fn=lambda sid: sop)
    out = sop_tools.sop_read("xyz9")
    assert "# Demo SOP (id=xyz9)" in out
    assert "alice" in out
    assert "step1" in out


def test_sop_read_empty_id():
    assert sop_tools.sop_read("").startswith("[sop_read error]")


def test_sop_read_engine_error(monkeypatch):
    def raise_err(sid):
        raise _FakeError("404")
    _patch_engine(monkeypatch, read_fn=raise_err, error_cls=_FakeError)
    out = sop_tools.sop_read("missing")
    assert out.startswith("[sop_read error]") and "404" in out


def test_sop_stats(monkeypatch):
    _patch_engine(monkeypatch, stats_fn=lambda: {"total": 1234, "api_url": "https://fudankw.cn/sophub"})
    out = sop_tools.sop_stats()
    assert "1234" in out and "fudankw.cn" in out
