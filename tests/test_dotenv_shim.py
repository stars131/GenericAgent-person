"""Tests for launcher.dotenv_shim."""
from __future__ import annotations

import os

import pytest

from launcher import dotenv_shim


# ──────────────────────────────────────────────────────────────────────────
# parse_env_file


def test_parse_basic_kv(tmp_path):
    p = tmp_path / ".env"
    p.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
    assert dotenv_shim.parse_env_file(str(p)) == {"FOO": "bar", "BAZ": "qux"}


def test_parse_skips_comments_and_blanks(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "# this is a comment\n"
        "\n"
        "FOO=bar\n"
        "  # indented comment\n"
        "BAZ=qux  # trailing comment\n",
        encoding="utf-8",
    )
    assert dotenv_shim.parse_env_file(str(p)) == {"FOO": "bar", "BAZ": "qux"}


def test_parse_handles_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        'DOUBLE="hello world"\n'
        "SINGLE='no $expansion # here'\n"
        'ESCAPE="line1\\nline2\\ttabbed"\n',
        encoding="utf-8",
    )
    out = dotenv_shim.parse_env_file(str(p))
    assert out["DOUBLE"] == "hello world"
    # Single-quoted values are taken literally — comments and dollars are not
    # interpreted.
    assert out["SINGLE"] == "no $expansion # here"
    assert out["ESCAPE"] == "line1\nline2\ttabbed"


def test_parse_export_prefix(tmp_path):
    p = tmp_path / ".env"
    p.write_text("export FOO=bar\nexport  SPACED=quux\n", encoding="utf-8")
    assert dotenv_shim.parse_env_file(str(p)) == {"FOO": "bar", "SPACED": "quux"}


def test_parse_missing_file_returns_empty(tmp_path):
    assert dotenv_shim.parse_env_file(str(tmp_path / "nope.env")) == {}


def test_parse_garbage_lines_dropped_silently(tmp_path):
    p = tmp_path / ".env"
    p.write_text("=novalue\n???not a key\nGOOD=ok\n", encoding="utf-8")
    out = dotenv_shim.parse_env_file(str(p))
    # Only GOOD survives — robustness over strictness.
    assert out == {"GOOD": "ok"}


# ──────────────────────────────────────────────────────────────────────────
# load_env


def test_load_env_does_not_clobber_shell_vars(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("FOO_TEST=fromfile\nNEW_TEST=created\n", encoding="utf-8")
    monkeypatch.setenv("FOO_TEST", "fromshell")
    n = dotenv_shim.load_env(str(p))
    assert os.environ["FOO_TEST"] == "fromshell"  # shell wins
    assert os.environ["NEW_TEST"] == "created"
    # Only the newly-created var is counted.
    assert n == 1


def test_load_env_override_replaces(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("FOO_OV=fromfile\n", encoding="utf-8")
    monkeypatch.setenv("FOO_OV", "fromshell")
    dotenv_shim.load_env(str(p), override=True)
    assert os.environ["FOO_OV"] == "fromfile"


# ──────────────────────────────────────────────────────────────────────────
# synthesize_mykeys


def test_synthesize_returns_empty_when_no_keys():
    assert dotenv_shim.synthesize_mykeys({}) == {}


def test_synthesize_openai_only():
    out = dotenv_shim.synthesize_mykeys({"OPENAI_API_KEY": "sk-test"})
    assert "native_oai_config_env" in out
    assert out["native_oai_config_env"]["apikey"] == "sk-test"
    assert out["native_oai_config_env"]["apibase"] == "https://api.openai.com/v1"
    # Synthetic mixin lets the launcher pick a session straight off.
    assert out["mixin_config"]["llm_nos"] == ["openai-env"]


def test_synthesize_anthropic_real_endpoint_no_fake_cc():
    out = dotenv_shim.synthesize_mykeys({"ANTHROPIC_API_KEY": "sk-ant-test"})
    cfg = out["native_claude_config_env"]
    assert cfg["apikey"] == "sk-ant-test"
    # Real Anthropic endpoint → must NOT set fake_cc_system_prompt
    assert "fake_cc_system_prompt" not in cfg


def test_synthesize_anthropic_relay_sets_fake_cc():
    # Non-sk-ant- prefix → relay/proxy → must enable CC fingerprint to pass
    # auth on the upstream's CC-switch validator.
    out = dotenv_shim.synthesize_mykeys({"ANTHROPIC_API_KEY": "cr_relaykey"})
    cfg = out["native_claude_config_env"]
    assert cfg["fake_cc_system_prompt"] is True


def test_synthesize_both_keys_creates_failover():
    out = dotenv_shim.synthesize_mykeys({
        "ANTHROPIC_API_KEY": "sk-ant-aa",
        "OPENAI_API_KEY": "sk-oo",
    })
    assert set(out["mixin_config"]["llm_nos"]) == {"anthropic-env", "openai-env"}


def test_synthesize_ga_prefix_takes_priority():
    out = dotenv_shim.synthesize_mykeys({
        "OPENAI_API_KEY": "sk-shared",
        "GA_OPENAI_API_KEY": "sk-ga-only",
    })
    assert out["native_oai_config_env"]["apikey"] == "sk-ga-only"


def test_synthesize_respects_custom_base_and_model():
    out = dotenv_shim.synthesize_mykeys({
        "OPENAI_API_KEY": "sk-x",
        "OPENAI_BASE_URL": "https://relay.local/v1",
        "OPENAI_MODEL": "gpt-5-mini",
    })
    cfg = out["native_oai_config_env"]
    assert cfg["apibase"] == "https://relay.local/v1"
    assert cfg["model"] == "gpt-5-mini"


# ──────────────────────────────────────────────────────────────────────────
# bootstrap


def test_bootstrap_uses_repo_root_path(monkeypatch, tmp_path):
    # bootstrap() points at <repo>/.env. Verify by stubbing _default_env_path.
    fake = tmp_path / "fake.env"
    fake.write_text("BOOTSTRAP_TEST=1\n", encoding="utf-8")
    monkeypatch.delenv("BOOTSTRAP_TEST", raising=False)
    monkeypatch.setattr(dotenv_shim, "_default_env_path", lambda: str(fake))
    n, path = dotenv_shim.bootstrap()
    assert n == 1
    assert path == str(fake)
    assert os.environ.get("BOOTSTRAP_TEST") == "1"


# ──────────────────────────────────────────────────────────────────────────
# integration with llmcore._load_mykeys
#
# We can't easily stub `import mykey` from a test (it's already imported by
# other tests), so we exercise the synthesis path via the public function
# and make sure it returns the same shape llmcore expects.


def test_synthesized_dict_is_well_formed_for_llmcore():
    """Spot-check: keys present in a synthesized dict should be the same
    kinds of keys ``agentmain.py`` scans for (containing 'api'/'config').
    Without this guarantee, the synthesized fallback wouldn't actually
    spawn any sessions even though it passed the load check."""
    out = dotenv_shim.synthesize_mykeys({"OPENAI_API_KEY": "sk-t"})
    for k in out:
        if k == "mixin_config":
            continue
        # Mirrors agentmain.py's filter: variable names containing 'config'
        # or 'api' are dispatched into Session classes.
        assert "config" in k or "api" in k
