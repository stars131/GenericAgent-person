from pathlib import Path

import pytest

from launcher.api_config import (
    apply_active_profile,
    delete_profile,
    load_api_configs,
    load_profiles,
    public_config,
    rename_profile,
    safe_config_var_name,
    save_api_configs,
    set_active_profile,
    upsert_profile,
    validate_config,
)


def test_safe_config_var_name():
    assert safe_config_var_name("native_oai", "GPT 4.1") == "native_oai_config_gpt_4_1"
    assert safe_config_var_name("native_claude", "123") == "native_claude_config_m_123"


def test_validate_requires_fields():
    ok, msg = validate_config({"kind": "native_oai", "name": "x"})
    assert not ok
    assert "apikey" in msg


def test_save_and_load_native_oai(tmp_path):
    cfg = {
        "kind": "native_oai",
        "name": "local",
        "apikey": "sk-test",
        "apibase": "https://example.com/v1",
        "model": "gpt-test",
        "stream": True,
    }
    saved = save_api_configs(str(tmp_path), [cfg])
    assert saved[0]["name"] == "local"
    loaded = load_api_configs(str(tmp_path))
    assert loaded[0]["apikey"] == "sk-test"
    override = Path(tmp_path) / "mykey_local_override.py"
    text = override.read_text(encoding="utf-8")
    assert "native_oai_config_local" in text
    assert "sk-test" in text


def test_public_config_masks_key():
    cfg = public_config({"kind": "native_oai", "name": "x", "apikey": "secret"})
    assert cfg["apikey"] == "***"


def test_invalid_config_not_saved(tmp_path):
    with pytest.raises(ValueError):
        save_api_configs(str(tmp_path), [{"kind": "native_oai", "name": "bad"}])


def _two_configs():
    return [
        {"kind": "native_oai", "name": "alpha", "apikey": "sk-a", "apibase": "https://x", "model": "m"},
        {"kind": "native_oai", "name": "beta", "apikey": "sk-b", "apibase": "https://y", "model": "m"},
    ]


def test_no_profile_writes_all_configs(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    text = (Path(tmp_path) / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "sk-a" in text and "sk-b" in text


def test_active_profile_filters_override(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    upsert_profile(str(tmp_path), "claude-only", ["beta"])
    set_active_profile(str(tmp_path), "claude-only")
    text = (Path(tmp_path) / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "sk-b" in text
    assert "sk-a" not in text


def test_set_active_none_falls_back_to_all(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    upsert_profile(str(tmp_path), "p", ["alpha"])
    set_active_profile(str(tmp_path), "p")
    set_active_profile(str(tmp_path), None)
    text = (Path(tmp_path) / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "sk-a" in text and "sk-b" in text


def test_rename_profile_keeps_active(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    upsert_profile(str(tmp_path), "old", ["alpha"])
    set_active_profile(str(tmp_path), "old")
    rename_profile(str(tmp_path), "old", "new")
    state = load_profiles(str(tmp_path))
    assert state["active"] == "new"
    assert state["profiles"]["new"] == ["alpha"]


def test_delete_active_profile_promotes_or_clears(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    upsert_profile(str(tmp_path), "p1", ["alpha"])
    upsert_profile(str(tmp_path), "p2", ["beta"])
    set_active_profile(str(tmp_path), "p1")
    delete_profile(str(tmp_path), "p1")
    state = load_profiles(str(tmp_path))
    assert state["active"] == "p2"
    delete_profile(str(tmp_path), "p2")
    assert load_profiles(str(tmp_path))["active"] is None


def test_save_configs_reapplies_active_profile(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    upsert_profile(str(tmp_path), "alpha-only", ["alpha"])
    set_active_profile(str(tmp_path), "alpha-only")
    # adding a new config should not leak into override unless profile membership grants it
    save_api_configs(str(tmp_path), [
        *_two_configs(),
        {"kind": "native_oai", "name": "gamma", "apikey": "sk-g", "apibase": "https://z", "model": "m"},
    ])
    text = (Path(tmp_path) / "mykey_local_override.py").read_text(encoding="utf-8")
    assert "sk-a" in text
    assert "sk-b" not in text
    assert "sk-g" not in text


def test_set_active_unknown_profile_raises(tmp_path):
    save_api_configs(str(tmp_path), _two_configs())
    with pytest.raises(ValueError):
        set_active_profile(str(tmp_path), "nope")
