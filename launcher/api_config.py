"""Launcher-managed API config cards and mykey_local_override.py generation."""
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

CONFIG_FILE = "launcher_api_configs.json"
PROFILES_FILE = "launcher_profiles.json"
SUPPORTED_KINDS = {"native_oai", "native_claude", "mixin"}
REQUIRED_FIELDS = {
    "native_oai": ("name", "apikey", "apibase", "model"),
    "native_claude": ("name", "apikey", "apibase", "model"),
    "mixin": ("name", "llm_nos"),
}
KIND_PREFIX = {
    "native_oai": "native_oai_config",
    "native_claude": "native_claude_config",
    "mixin": "mixin_config",
}
COMMON_OPTIONAL_FIELDS = (
    "api_mode",
    "stream",
    "max_tokens",
    "max_retries",
    "connect_timeout",
    "read_timeout",
    "reasoning_effort",
    "thinking_type",
    "thinking_budget_tokens",
    "fake_cc_system_prompt",
)


def config_path(base_dir):
    return os.path.join(base_dir, "temp", CONFIG_FILE)


def profiles_path(base_dir):
    return os.path.join(base_dir, "temp", PROFILES_FILE)


def override_path(base_dir):
    return os.path.join(base_dir, "mykey_local_override.py")


def _ensure_temp(base_dir):
    os.makedirs(os.path.join(base_dir, "temp"), exist_ok=True)


def load_api_configs(base_dir):
    path = config_path(base_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    configs = data.get("configs", data if isinstance(data, list) else [])
    return [normalize_config(c) for c in configs if isinstance(c, dict)]


def save_api_configs(base_dir, configs):
    normalized = [normalize_config(c) for c in configs if isinstance(c, dict)]
    for config in normalized:
        ok, msg = validate_config(config)
        if not ok:
            raise ValueError(msg)
    _ensure_temp(base_dir)
    path = config_path(base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"configs": normalized}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    apply_active_profile(base_dir)
    return normalized


def load_profiles(base_dir):
    path = profiles_path(base_dir)
    if not os.path.isfile(path):
        return {"active": None, "profiles": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"active": None, "profiles": {}}
    profiles = data.get("profiles") or {}
    return {
        "active": data.get("active") if isinstance(data.get("active"), str) else None,
        "profiles": {
            str(k): [str(name) for name in v if isinstance(name, str)]
            for k, v in profiles.items()
            if isinstance(v, list)
        },
    }


def save_profiles(base_dir, data):
    _ensure_temp(base_dir)
    profiles = data.get("profiles") or {}
    active = data.get("active")
    if active not in profiles:
        active = None
    payload = {"active": active, "profiles": profiles}
    path = profiles_path(base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return payload


def list_profiles(base_dir):
    return load_profiles(base_dir)


def apply_active_profile(base_dir):
    """Rewrite mykey_local_override.py based on the active profile.

    No profile or no active profile → write all configs (legacy behavior).
    Active profile → write only configs whose name is in profiles[active].
    """
    configs = load_api_configs(base_dir)
    state = load_profiles(base_dir)
    active = state.get("active")
    members = state.get("profiles", {}).get(active or "")
    if active and isinstance(members, list):
        wanted = set(members)
        filtered = [c for c in configs if c.get("name") in wanted]
    else:
        filtered = configs
    return write_mykey_override(base_dir, filtered)


def set_active_profile(base_dir, name):
    state = load_profiles(base_dir)
    if name is not None and name not in state.get("profiles", {}):
        raise ValueError(f"profile not found: {name}")
    state["active"] = name
    save_profiles(base_dir, state)
    apply_active_profile(base_dir)
    return state


def upsert_profile(base_dir, name, member_names):
    name = str(name or "").strip()
    if not name:
        raise ValueError("profile name required")
    state = load_profiles(base_dir)
    state["profiles"][name] = [str(n) for n in (member_names or [])]
    save_profiles(base_dir, state)
    if state.get("active") == name:
        apply_active_profile(base_dir)
    return state


def rename_profile(base_dir, old_name, new_name):
    new_name = str(new_name or "").strip()
    if not new_name:
        raise ValueError("new profile name required")
    state = load_profiles(base_dir)
    profiles = state.get("profiles", {})
    if old_name not in profiles:
        raise ValueError(f"profile not found: {old_name}")
    if new_name in profiles and new_name != old_name:
        raise ValueError(f"profile already exists: {new_name}")
    profiles[new_name] = profiles.pop(old_name)
    if state.get("active") == old_name:
        state["active"] = new_name
    save_profiles(base_dir, state)
    return state


def delete_profile(base_dir, name):
    state = load_profiles(base_dir)
    state.get("profiles", {}).pop(name, None)
    if state.get("active") == name:
        remaining = list(state.get("profiles", {}).keys())
        state["active"] = remaining[0] if remaining else None
    save_profiles(base_dir, state)
    apply_active_profile(base_dir)
    return state


def list_api_configs(base_dir):
    return [public_config(c) for c in load_api_configs(base_dir)]


def normalize_config(config):
    c = dict(config or {})
    c["kind"] = str(c.get("kind") or "native_oai").strip()
    c["name"] = str(c.get("name") or "").strip()
    if c["kind"] == "mixin" and isinstance(c.get("llm_nos"), str):
        c["llm_nos"] = [int(x.strip()) for x in c["llm_nos"].split(",") if x.strip().isdigit()]
    for key in ("stream", "fake_cc_system_prompt"):
        if isinstance(c.get(key), str):
            c[key] = c[key].strip().lower() in {"1", "true", "yes", "on"}
    for key in ("max_tokens", "max_retries", "connect_timeout", "read_timeout", "thinking_budget_tokens"):
        if isinstance(c.get(key), str) and c[key].strip():
            try:
                c[key] = int(c[key]) if key in {"max_tokens", "max_retries", "thinking_budget_tokens"} else float(c[key])
            except ValueError:
                pass
    return c


def public_config(config):
    c = dict(config)
    if c.get("apikey"):
        c["apikey"] = "***"
    c["var_name"] = safe_config_var_name(c.get("kind"), c.get("name"))
    return c


def validate_config(config):
    kind = str(config.get("kind") or "").strip()
    if kind not in SUPPORTED_KINDS:
        return False, f"unsupported config kind: {kind}"
    for field in REQUIRED_FIELDS[kind]:
        value = config.get(field)
        if value is None or value == "" or value == []:
            return False, f"missing required field: {field}"
    return True, ""


def safe_config_var_name(kind, name):
    prefix = KIND_PREFIX.get(str(kind or ""), "native_oai_config")
    slug = re.sub(r"\W+", "_", str(name or "default").strip().lower()).strip("_")
    slug = slug or "default"
    if slug[0].isdigit():
        slug = "m_" + slug
    return f"{prefix}_{slug}"


def _config_payload(config):
    kind = config.get("kind")
    if kind == "mixin":
        keys = ("name", "llm_nos", "max_retries", "base_delay", "spring_back")
    else:
        keys = ("name", "apikey", "apibase", "model", *COMMON_OPTIONAL_FIELDS)
    return {k: config[k] for k in keys if k in config and config[k] not in ("", None, [])}


def write_mykey_override(base_dir, configs):
    lines = [
        "# Auto-generated by GenericAgent Qt Launcher.",
        "# Edit through the launcher UI; manual changes may be overwritten.",
        "",
    ]
    used = set()
    for raw in configs:
        config = normalize_config(raw)
        ok, msg = validate_config(config)
        if not ok:
            raise ValueError(msg)
        name = safe_config_var_name(config["kind"], config["name"])
        base, idx = name, 2
        while name in used:
            name = f"{base}_{idx}"
            idx += 1
        used.add(name)
        lines.append(f"{name} = {repr(_config_payload(config))}")
        lines.append("")
    path = override_path(base_dir)
    new_text = "\n".join(lines)
    _backup_if_changed(base_dir, path, new_text)
    Path(path).write_text(new_text, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def _backup_if_changed(base_dir, path, new_text, keep=3):
    if not os.path.isfile(path):
        return
    try:
        if Path(path).read_text(encoding="utf-8") == new_text:
            return
    except OSError:
        return
    backup_dir = os.path.join(base_dir, "temp")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(backup_dir, f"mykey_local_override.py.bak.{stamp}")
    try:
        shutil.copy2(path, backup)
    except OSError:
        return
    backups = sorted(
        p for p in os.listdir(backup_dir)
        if p.startswith("mykey_local_override.py.bak.")
    )
    for old in backups[:-keep]:
        try:
            os.remove(os.path.join(backup_dir, old))
        except OSError:
            pass
