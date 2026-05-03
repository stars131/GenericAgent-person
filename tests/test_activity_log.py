"""Tests for launcher.activity_log + the /api/activity endpoint pair."""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.request

import pytest

from launcher import activity_log, api_server


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GA_ACTIVITY_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("GA_ACTIVITY_LOG_OFF", raising=False)
    # Reset day-trim sentinel so each test gets a clean trim cycle.
    monkeypatch.setattr(activity_log, "_LAST_TRIM_DAY", None)
    yield


def test_record_writes_jsonl_with_metadata():
    activity_log.record({"phase": "tool_start", "turn": 1, "tool": "file_read"})
    path = activity_log.latest_path()
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as f:
        line = f.readline()
    obj = json.loads(line)
    assert obj["phase"] == "tool_start"
    assert obj["turn"] == 1
    assert obj["tool"] == "file_read"
    assert obj["pid"] == os.getpid()
    assert obj["ts"].endswith("Z")


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("GA_ACTIVITY_LOG_OFF", "1")
    activity_log.record({"phase": "tool_start", "turn": 1, "tool": "x"})
    assert not os.path.isfile(activity_log.latest_path())


def test_compact_args_strips_internals_and_clips_long_strings():
    out = activity_log.compact_args("file_read", {"_index": 7, "path": "x", "blob": "a" * 1000})
    assert "_index" not in out
    assert out["path"] == "x"
    assert out["blob"].startswith("a" * 400)
    assert "+600 chars" in out["blob"]


def test_iter_recent_returns_chronological_tail():
    for i in range(5):
        activity_log.record({"phase": "turn_end", "turn": i})
    events = activity_log.iter_recent(limit=3)
    assert [e["turn"] for e in events] == [2, 3, 4]


def test_record_never_raises_on_bad_payload():
    # Sets cannot be serialized natively; default=str must catch.
    activity_log.record({"phase": "x", "weird": {1, 2, 3}})
    events = activity_log.iter_recent(10)
    assert events and events[-1]["phase"] == "x"


@pytest.fixture(scope="module")
def live_server():
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


def test_activity_endpoint_returns_recent_events(live_server: int):
    activity_log.record({"phase": "tool_start", "turn": 99, "tool": "ping"})
    data = _get_json(live_server, "/api/activity?limit=10")
    assert "events" in data
    tools = [e.get("tool") for e in data["events"] if e.get("tool")]
    assert "ping" in tools


def test_activity_stream_emits_meta_then_appends(live_server: int):
    # Pre-create the file so the SSE handler skips the wait-for-file branch.
    activity_log.record({"phase": "tool_start", "turn": 1, "tool": "seed"})

    conn = http.client.HTTPConnection("127.0.0.1", live_server, timeout=5)
    conn.request("GET", "/api/activity/stream")
    resp = conn.getresponse()
    assert resp.status == 200
    assert "text/event-stream" in resp.headers.get("Content-Type", "")

    events: list[tuple[str, str]] = []
    buf = b""
    deadline = time.monotonic() + 5.0
    fp = resp.fp  # type: ignore[attr-defined]
    try:
        while len(events) < 2 and time.monotonic() < deadline:
            chunk = fp.read1(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                event_name = ""
                data_lines: list[str] = []
                for line in frame.decode("utf-8").splitlines():
                    if line.startswith("event: "):
                        event_name = line[len("event: "):]
                    elif line.startswith("data: "):
                        data_lines.append(line[len("data: "):])
                events.append((event_name, "\n".join(data_lines)))
    finally:
        conn.close()

    names = [e[0] for e in events]
    assert "meta" in names
    payload = "\n".join(d for _, d in events)
    assert "seed" in payload


# ---- skill outcome aggregation -------------------------------------------


def _record_turn(skill: str | None, result: str, ts_offset: int = 0):
    activity_log.record({
        "phase": "turn_end",
        "turn": 1,
        "summary": "x",
        "exit_reason": {"result": result},
        "related_sop": skill or "",
    })


def test_summarize_outcomes_groups_by_skill():
    _record_turn("web_setup_sop", "CURRENT_TASK_DONE")
    _record_turn("web_setup_sop", "CURRENT_TASK_DONE")
    _record_turn("web_setup_sop", "MAX_TURNS_EXCEEDED")
    _record_turn("plan_sop", "EXITED")
    _record_turn(None, "CURRENT_TASK_DONE")

    summary = activity_log.summarize_outcomes()
    assert summary["web_setup_sop"]["ok"] == 2
    assert summary["web_setup_sop"]["max_turns"] == 1
    assert summary["web_setup_sop"]["total"] == 3
    # success_rate = ok / (ok + max_turns + other) = 2 / 3
    assert abs(summary["web_setup_sop"]["success_rate"] - (2 / 3)) < 1e-9
    # Pure exited turns have no terminal denominator → success_rate is None.
    assert summary["plan_sop"]["exited"] == 1
    assert summary["plan_sop"]["success_rate"] is None
    assert summary["_unattributed"]["ok"] == 1


def test_summarize_outcomes_skips_non_turn_end_and_no_exit():
    activity_log.record({"phase": "tool_start", "turn": 1, "tool": "x"})
    activity_log.record({"phase": "turn_end", "turn": 1, "exit_reason": {}, "related_sop": "x"})
    summary = activity_log.summarize_outcomes()
    # Neither event should produce a skill entry: the first is wrong phase,
    # the second has no terminal exit_reason.
    assert summary == {}


def test_skill_outcomes_endpoint(live_server: int):
    _record_turn("github_contribution_sop", "CURRENT_TASK_DONE")
    _record_turn("github_contribution_sop", "MAX_TURNS_EXCEEDED")
    data = _get_json(live_server, "/api/skills/outcomes")
    assert "skills" in data
    by_name = {s["name"]: s for s in data["skills"]}
    assert "github_contribution_sop" in by_name
    entry = by_name["github_contribution_sop"]
    assert entry["ok"] == 1
    assert entry["max_turns"] == 1
    assert entry["total"] == 2
    assert abs(entry["success_rate"] - 0.5) < 1e-9
