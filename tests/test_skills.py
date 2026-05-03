"""Tests for launcher.skills + the /api/skills endpoint."""
from __future__ import annotations

import json
import os
import urllib.request

import pytest

from launcher import activity_log, api_server, skills


@pytest.fixture
def fake_memory(tmp_path, monkeypatch):
    """Point the skills scanner + activity log at isolated dirs."""
    mem = tmp_path / "memory"
    mem.mkdir()
    activity = tmp_path / "activity"
    activity.mkdir()
    monkeypatch.setenv("GA_MEMORY_DIR", str(mem))
    monkeypatch.setenv("GA_ACTIVITY_LOG_DIR", str(activity))
    monkeypatch.delenv("GA_ACTIVITY_LOG_OFF", raising=False)
    monkeypatch.setattr(activity_log, "_LAST_TRIM_DAY", None)
    return mem


def _write_sop(mem, name: str, body: str) -> None:
    (mem / name).write_text(body, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────
# normalize_related_sop


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("web_setup_sop", "web_setup_sop"),
        ("memory/web_setup_sop.md", "web_setup_sop"),
        ("memory\\web_setup_sop.md", "web_setup_sop"),
        ("web_setup_sop, plan_sop", "web_setup_sop"),
        ("  plan_sop  ", "plan_sop"),
        ("./memory/subagent.md", "subagent"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_related_sop(raw, expected):
    assert activity_log.normalize_related_sop(raw) == expected


def test_summarize_outcomes_normalizes_path_form(fake_memory, monkeypatch):
    # Agents that wrote the full path used to land in a separate bucket from
    # bare-stem writers — normalization fixes that.
    activity_log.record({
        "phase": "turn_end",
        "turn": 1,
        "exit_reason": {"result": "CURRENT_TASK_DONE"},
        "related_sop": "memory/web_setup_sop.md",
    })
    activity_log.record({
        "phase": "turn_end",
        "turn": 2,
        "exit_reason": {"result": "CURRENT_TASK_DONE"},
        "related_sop": "web_setup_sop",
    })
    summary = activity_log.summarize_outcomes()
    assert "web_setup_sop" in summary
    assert summary["web_setup_sop"]["ok"] == 2
    # No leakage into a path-shaped key.
    assert all("/" not in k and not k.endswith(".md") for k in summary)


# ──────────────────────────────────────────────────────────────────────────
# list_skills — filesystem


def test_list_skills_picks_up_sop_files_only(fake_memory):
    _write_sop(fake_memory, "web_setup_sop.md", "# Web 工具链初始化\nFirst paragraph.\n")
    _write_sop(fake_memory, "subagent.md", "# Subagent 调用 SOP\n")
    _write_sop(fake_memory, "README.md", "# Readme — should be ignored\n")
    _write_sop(fake_memory, "notes.md", "# notes — should be ignored\n")

    items = skills.list_skills()
    names = [it["name"] for it in items]
    assert "web_setup_sop" in names
    assert "subagent" in names
    assert "README" not in names
    assert "notes" not in names


def test_list_skills_extracts_title_and_subtitle(fake_memory):
    _write_sop(
        fake_memory,
        "plan_sop.md",
        "# Plan SOP\n\nDecompose tasks before execution.\nKeep checklists.\n\n## Step 1\n",
    )
    items = skills.list_skills()
    entry = next(it for it in items if it["name"] == "plan_sop")
    assert entry["title"] == "Plan SOP"
    assert "Decompose tasks before execution" in entry["subtitle"]
    # Subtitle stops at the next heading, never bleeds into "## Step 1".
    assert "Step 1" not in entry["subtitle"]


def test_list_skills_handles_missing_title(fake_memory):
    _write_sop(fake_memory, "no_title_sop.md", "Just plain prose, no heading at all.\n")
    items = skills.list_skills()
    entry = next(it for it in items if it["name"] == "no_title_sop")
    # Falls back to the stem so the UI always has something to render.
    assert entry["title"] == "no_title_sop"


def test_list_skills_includes_metadata(fake_memory):
    _write_sop(fake_memory, "verify_sop.md", "# Verify\n\nbody\n")
    items = skills.list_skills()
    entry = next(it for it in items if it["name"] == "verify_sop")
    assert entry["size_bytes"] > 0
    assert entry["mtime"].endswith("Z")
    assert entry["path"].endswith("verify_sop.md")


# ──────────────────────────────────────────────────────────────────────────
# list_skills — outcome merging


def _record_turn_end(skill: str | None, result: str):
    activity_log.record({
        "phase": "turn_end",
        "turn": 1,
        "exit_reason": {"result": result},
        "related_sop": skill or "",
    })


def test_list_skills_merges_outcome_counts(fake_memory):
    _write_sop(fake_memory, "web_setup_sop.md", "# Web Setup\n")
    _write_sop(fake_memory, "plan_sop.md", "# Plan\n")
    _record_turn_end("web_setup_sop", "CURRENT_TASK_DONE")
    _record_turn_end("web_setup_sop", "MAX_TURNS_EXCEEDED")
    _record_turn_end("memory/web_setup_sop.md", "CURRENT_TASK_DONE")

    items = skills.list_skills()
    by_name = {it["name"]: it for it in items}
    web = by_name["web_setup_sop"]["outcomes"]
    assert web["ok"] == 2
    assert web["max_turns"] == 1
    assert web["total"] == 3
    # Plan SOP exists but was never invoked → outcomes is None so the UI can
    # render a "never used" state without a divide-by-zero on success_rate.
    assert by_name["plan_sop"]["outcomes"] is None


def test_list_skills_sorts_by_invocations_then_name(fake_memory):
    _write_sop(fake_memory, "alpha_sop.md", "# alpha\n")
    _write_sop(fake_memory, "beta_sop.md", "# beta\n")
    _write_sop(fake_memory, "gamma_sop.md", "# gamma\n")
    _record_turn_end("beta_sop", "CURRENT_TASK_DONE")
    _record_turn_end("beta_sop", "CURRENT_TASK_DONE")
    _record_turn_end("gamma_sop", "CURRENT_TASK_DONE")

    items = skills.list_skills()
    names = [it["name"] for it in items if it["name"] != "_unattributed"]
    # beta=2 invocations, gamma=1, alpha=0 → beta, gamma, alpha
    assert names == ["beta_sop", "gamma_sop", "alpha_sop"]


def test_list_skills_appends_unattributed_bucket(fake_memory):
    _write_sop(fake_memory, "alpha_sop.md", "# alpha\n")
    _record_turn_end(None, "CURRENT_TASK_DONE")  # related_sop=""
    items = skills.list_skills()
    assert items[-1]["name"] == "_unattributed"
    assert items[-1]["outcomes"]["ok"] == 1
    # Real skills never carry the bucket title.
    assert all(it["title"] != "(no skill attributed)" for it in items[:-1])


def test_list_skills_returns_empty_when_memory_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GA_MEMORY_DIR", str(tmp_path / "does_not_exist"))
    monkeypatch.setenv("GA_ACTIVITY_LOG_DIR", str(tmp_path / "activity_unused"))
    assert skills.list_skills() == []


# ──────────────────────────────────────────────────────────────────────────
# /api/skills endpoint


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


def test_skills_endpoint_returns_catalogue(live_server: int, fake_memory):
    _write_sop(fake_memory, "scheduled_task_sop.md", "# Scheduled Task\n\nWhat it does.\n")
    _record_turn_end("scheduled_task_sop", "CURRENT_TASK_DONE")
    data = _get_json(live_server, "/api/skills")
    assert "skills" in data
    by_name = {s["name"]: s for s in data["skills"]}
    assert "scheduled_task_sop" in by_name
    entry = by_name["scheduled_task_sop"]
    assert entry["title"] == "Scheduled Task"
    assert entry["outcomes"]["ok"] == 1
    assert os.path.basename(entry["path"]) == "scheduled_task_sop.md"
