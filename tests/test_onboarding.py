"""Tests for launcher.onboarding + the /api/onboarding/* endpoints."""
from __future__ import annotations

import importlib
import json
import urllib.request
import urllib.error

import pytest

from launcher import onboarding


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Redirect the wizard to a per-test ``.env`` file."""
    p = tmp_path / ".env"
    monkeypatch.setenv("GA_ENV_FILE", str(p))
    yield p


@pytest.fixture
def isolate_env(monkeypatch):
    """Wipe inherited keys so synthesize_mykeys doesn't accidentally
    classify the runner's shell as 'already configured'."""
    for var in (
        "OPENAI_API_KEY", "GA_OPENAI_API_KEY",
        "ANTHROPIC_API_KEY", "GA_ANTHROPIC_API_KEY",
        "OPENAI_BASE_URL", "OPENAI_MODEL",
        "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# ──────────────────────────────────────────────────────────────────────────
# placeholder detection


@pytest.mark.parametrize("value", [
    "",
    "<your-openai-key>",
    "sk-YOUR-KEY",
    "sk-user-<your-relay-key>",
    "sk-ant-<your-anthropic-key>",
    "cr_<your-crs-key>",
])
def test_is_placeholder_detects_template_strings(value):
    assert onboarding._is_placeholder(value)


@pytest.mark.parametrize("value", [
    "sk-real-1234567890abcdef",
    "sk-ant-api03-realkey",
    "cr_abc123def456",
])
def test_is_placeholder_passes_real_keys(value):
    assert not onboarding._is_placeholder(value)


# ──────────────────────────────────────────────────────────────────────────
# _has_real_session


def test_has_real_session_skips_mixin_container():
    """Mixin doesn't carry its own apikey — it points at other named
    sessions. A mykeys dict containing only mixin_config + placeholder
    sub-configs is NOT 'configured'."""
    mk = {
        "mixin_config": {"llm_nos": ["x"]},
        "native_oai_config": {"apikey": "<your-openai-key>"},
    }
    assert onboarding._has_real_session(mk) is False


def test_has_real_session_finds_real_key():
    mk = {"native_oai_config": {"apikey": "sk-realtoken-xyz"}}
    assert onboarding._has_real_session(mk) is True


def test_has_real_session_ignores_non_config_keys():
    """Variables that don't match the dispatcher's filter (no api/config/cookie
    in the name) shouldn't be inspected even if they have an apikey."""
    mk = {"some_random_dict": {"apikey": "sk-realtoken"}}
    assert onboarding._has_real_session(mk) is False


# ──────────────────────────────────────────────────────────────────────────
# status


def test_status_real_repo_with_mykey_returns_no_setup_needed():
    # The dev repo has mykey.py + mykey_local_override.py with real keys.
    s = onboarding.status()
    assert s["needs_setup"] is False
    assert s["has_mykey"] is True


def test_status_synthesized_from_env(monkeypatch, isolate_env):
    """When mykey.py would yield placeholders only but the env has a
    recognized key, synthesize_mykeys takes over and onboarding is
    considered 'done' (env_recognized=True, needs_setup=False)."""
    # Force has_real_session to fail so the env path is exercised.
    monkeypatch.setattr(onboarding, "_has_real_session", lambda mk: False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-from-env")
    s = onboarding.status()
    assert s["needs_setup"] is False
    assert s["env_recognized"] is True


def test_status_first_run_no_keys_anywhere(monkeypatch, isolate_env):
    monkeypatch.setattr(onboarding, "_has_real_session", lambda mk: False)
    s = onboarding.status()
    assert s["needs_setup"] is True
    # Reason carries something the GUI can show as a hint.
    assert s["reason"]


def test_status_handles_mykey_load_failure(monkeypatch):
    import llmcore
    def boom():
        raise RuntimeError("bad python in mykey.py")
    monkeypatch.setattr(llmcore, "reload_mykeys", boom)
    s = onboarding.status()
    assert s["needs_setup"] is True
    assert "bad python in mykey.py" in s["reason"]


# ──────────────────────────────────────────────────────────────────────────
# save_minimal — file writes


def test_save_minimal_writes_env_file(env_file, isolate_env):
    onboarding.save_minimal("openai", apikey="sk-mykey", base_url="", model="")
    text = env_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-mykey" in text
    # Defaults applied when caller leaves base/model blank.
    assert "OPENAI_BASE_URL=https://api.openai.com/v1" in text
    assert "OPENAI_MODEL=gpt-5.4" in text


def test_save_minimal_uses_custom_base_and_model(env_file, isolate_env):
    onboarding.save_minimal(
        "openai", apikey="sk-x", base_url="https://relay.local/v1", model="gpt-5-mini",
    )
    text = env_file.read_text(encoding="utf-8")
    assert "OPENAI_BASE_URL=https://relay.local/v1" in text
    assert "OPENAI_MODEL=gpt-5-mini" in text


def test_save_minimal_anthropic(env_file, isolate_env):
    onboarding.save_minimal("anthropic", apikey="sk-ant-real", base_url="", model="")
    text = env_file.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-real" in text
    assert "ANTHROPIC_BASE_URL=https://api.anthropic.com" in text


def test_save_minimal_patches_in_place_preserving_other_lines(env_file, isolate_env):
    # User already has a .env with an unrelated var + a stale OPENAI key.
    env_file.write_text(
        "# my dev .env\n"
        "OTHER_VAR=keepme\n"
        "OPENAI_API_KEY=sk-stale\n"
        "\n"
        "# trailing comment\n",
        encoding="utf-8",
    )
    onboarding.save_minimal("openai", apikey="sk-fresh", base_url="", model="")
    text = env_file.read_text(encoding="utf-8")
    # Stale key replaced in place, comment + other var preserved.
    assert "OPENAI_API_KEY=sk-fresh" in text
    assert "OPENAI_API_KEY=sk-stale" not in text
    assert "OTHER_VAR=keepme" in text
    assert "# my dev .env" in text


def test_save_minimal_seeds_os_environ(env_file, isolate_env):
    """The wizard's whole point is letting the user run the agent without
    a restart, so the env vars must be live in this process."""
    import os
    onboarding.save_minimal("openai", apikey="sk-live", base_url="", model="")
    assert os.environ["OPENAI_API_KEY"] == "sk-live"


def test_save_minimal_rejects_empty_key(env_file, isolate_env):
    with pytest.raises(ValueError, match="apikey is required"):
        onboarding.save_minimal("openai", apikey="", base_url="", model="")


def test_save_minimal_rejects_unknown_provider(env_file, isolate_env):
    with pytest.raises(ValueError, match="unknown provider"):
        onboarding.save_minimal("cohere", apikey="sk-x", base_url="", model="")


def test_save_minimal_quotes_value_with_spaces(env_file, isolate_env):
    """Values with whitespace must be quoted or the .env parser breaks."""
    onboarding.save_minimal(
        "openai", apikey="sk-x", base_url="https://relay.local/v1 weird", model="",
    )
    text = env_file.read_text(encoding="utf-8")
    assert 'OPENAI_BASE_URL="https://relay.local/v1 weird"' in text


# ──────────────────────────────────────────────────────────────────────────
# /api/onboarding/* endpoints


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


def _post_json(port: int, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_endpoint_status_reachable(live_server: int):
    data = _get_json(live_server, "/api/onboarding/status")
    assert "needs_setup" in data
    assert "providers" in data
    assert "openai" in data["providers"]


def test_endpoint_save_validation_400(live_server: int):
    code, body = _post_json(live_server, "/api/onboarding/save", {
        "provider": "openai", "apikey": "",
    })
    assert code == 400
    assert "error" in body


def test_endpoint_save_round_trip(live_server: int, env_file, isolate_env):
    code, body = _post_json(live_server, "/api/onboarding/save", {
        "provider": "openai",
        "apikey": "sk-from-endpoint",
        "base_url": "",
        "model": "",
    })
    assert code == 200
    # Endpoint returns the fresh status snapshot.
    assert "needs_setup" in body
    assert env_file.read_text(encoding="utf-8").find("sk-from-endpoint") != -1
