"""Tests for llmcore's token-usage counters + /api/token_usage endpoint."""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest

import llmcore


@pytest.fixture(autouse=True)
def reset_counters():
    llmcore.reset_token_usage()
    yield
    llmcore.reset_token_usage()


# ──────────────────────────────────────────────────────────────────────────
# _accumulate_usage / get_token_usage


def test_initial_snapshot_is_zero():
    snap = llmcore.get_token_usage()
    assert snap["totals"]["input"] == 0
    assert snap["totals"]["output"] == 0
    assert snap["totals"]["calls"] == 0
    # Cache hit rate is None when nothing has been recorded — divide-by-zero
    # protection. The GUI relies on this to render "—" instead of "0%".
    assert snap["cache_hit_rate"] is None
    assert snap["recent"] == []


def test_accumulate_messages_mode():
    llmcore._accumulate_usage("messages", input_tokens=100, output_tokens=50,
                              cache_creation=200, cache_read=800)
    snap = llmcore.get_token_usage()
    assert snap["totals"]["input"] == 100
    assert snap["totals"]["output"] == 50
    assert snap["totals"]["cache_creation"] == 200
    assert snap["totals"]["cache_read"] == 800
    assert snap["totals"]["calls"] == 1
    # cache_read / (input + cache_creation + cache_read) = 800 / 1100
    assert abs(snap["cache_hit_rate"] - (800 / 1100)) < 1e-9


def test_accumulate_multiple_calls_sums():
    for i in range(5):
        llmcore._accumulate_usage("messages", input_tokens=10, output_tokens=5)
    snap = llmcore.get_token_usage()
    assert snap["totals"]["input"] == 50
    assert snap["totals"]["output"] == 25
    assert snap["totals"]["calls"] == 5
    assert len(snap["recent"]) == 5


def test_accumulate_separates_by_mode():
    llmcore._accumulate_usage("messages", input_tokens=100, output_tokens=10)
    llmcore._accumulate_usage("chat_completions", input_tokens=200, output_tokens=20)
    llmcore._accumulate_usage("responses", input_tokens=300, output_tokens=30)
    snap = llmcore.get_token_usage()
    assert snap["by_mode"]["messages"]["input"] == 100
    assert snap["by_mode"]["chat_completions"]["input"] == 200
    assert snap["by_mode"]["responses"]["input"] == 300
    # Totals fold across modes.
    assert snap["totals"]["input"] == 600
    assert snap["totals"]["output"] == 60


def test_recent_buffer_is_bounded():
    cap = llmcore._USAGE_RECENT_CAP
    for i in range(cap + 50):
        llmcore._accumulate_usage("messages", input_tokens=1)
    snap = llmcore.get_token_usage()
    # Buffer never exceeds the cap; oldest are evicted.
    assert len(snap["recent"]) == cap
    # Calls counter is *not* bounded — it tracks the true total.
    assert snap["totals"]["calls"] == cap + 50


def test_accumulate_swallows_bad_input():
    # None values used to raise on int() — the wrapper has to handle them
    # because the SSE parsers occasionally pass missing keys defaulted to 0
    # via .get(). Plus we want the counter to never break the agent loop.
    llmcore._accumulate_usage("messages", input_tokens=None, output_tokens=None)  # type: ignore[arg-type]
    snap = llmcore.get_token_usage()
    assert snap["totals"]["calls"] == 1
    assert snap["totals"]["input"] == 0


def test_reset_clears_everything():
    llmcore._accumulate_usage("messages", input_tokens=100, output_tokens=50)
    llmcore.reset_token_usage()
    snap = llmcore.get_token_usage()
    assert snap["totals"]["calls"] == 0
    assert snap["by_mode"] == {}
    assert snap["recent"] == []


# ──────────────────────────────────────────────────────────────────────────
# Wired into _record_usage (the existing SSE/JSON parser hook)


def test_record_usage_messages_mode_records_full_set():
    """Mirrors what _parse_claude_sse passes in on a real Anthropic stream."""
    usage = {
        "input_tokens": 120,
        "output_tokens": 80,
        "cache_creation_input_tokens": 40,
        "cache_read_input_tokens": 1000,
    }
    llmcore._record_usage(usage, "messages")
    snap = llmcore.get_token_usage()
    assert snap["totals"]["input"] == 120
    assert snap["totals"]["output"] == 80
    assert snap["totals"]["cache_creation"] == 40
    assert snap["totals"]["cache_read"] == 1000


def test_record_usage_chat_completions_records_input_and_output():
    """OAI ``chat_completions`` returns ``prompt_tokens`` / ``completion_tokens``
    plus an optional ``prompt_tokens_details.cached_tokens`` for cache hits."""
    usage = {
        "prompt_tokens": 500,
        "completion_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 300},
    }
    llmcore._record_usage(usage, "chat_completions")
    snap = llmcore.get_token_usage()
    assert snap["totals"]["input"] == 500
    assert snap["totals"]["output"] == 100
    assert snap["totals"]["cache_read"] == 300


def test_record_usage_empty_does_nothing():
    llmcore._record_usage({}, "messages")
    llmcore._record_usage(None, "messages")
    snap = llmcore.get_token_usage()
    assert snap["totals"]["calls"] == 0


# ──────────────────────────────────────────────────────────────────────────
# /api/token_usage endpoint


@pytest.fixture(scope="module")
def live_server():
    from launcher import api_server
    last_err: Exception | None = None
    for _ in range(5):
        try:
            port, _thread = api_server.serve_threaded()
            break
        except (OSError, PermissionError) as exc:
            last_err = exc
            continue
    else:
        raise RuntimeError(f"could not start api_server: {last_err}")
    yield port


def _get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as resp:
        assert resp.status == 200
        return json.loads(resp.read())


def _post_json(port: int, path: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"",
                                 method="POST")
    with urllib.request.urlopen(req, timeout=2) as resp:
        assert resp.status == 200
        return json.loads(resp.read())


def test_endpoint_returns_zero_snapshot(live_server: int):
    data = _get_json(live_server, "/api/token_usage")
    assert "totals" in data
    assert data["totals"]["calls"] == 0


def test_endpoint_reflects_accumulation(live_server: int):
    llmcore._accumulate_usage("messages", input_tokens=42, output_tokens=7)
    data = _get_json(live_server, "/api/token_usage")
    assert data["totals"]["input"] == 42
    assert data["totals"]["output"] == 7
    assert data["totals"]["calls"] == 1


def test_endpoint_reset_clears_counters(live_server: int):
    llmcore._accumulate_usage("messages", input_tokens=999, output_tokens=111)
    data = _post_json(live_server, "/api/token_usage/reset")
    assert data["totals"]["calls"] == 0
    follow = _get_json(live_server, "/api/token_usage")
    assert follow["totals"]["calls"] == 0
