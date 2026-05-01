from launcher.project_manager import ProjectManager
from launcher.launch_config import load_options, save_options


def test_project_metadata_defaults(tmp_path):
    pm = ProjectManager(str(tmp_path))
    project = pm.create("one", auto_start=False)
    assert project["pinned"] is False
    assert project["description"] == ""
    assert project["updated_at"]


def test_pin_persists_and_sorts_first(tmp_path):
    pm = ProjectManager(str(tmp_path))
    first = pm.create("first", auto_start=False)
    second = pm.create("second", auto_start=False)
    assert pm.pin(first["id"], True)
    rows = pm.list()["projects"]
    assert rows[0]["id"] == first["id"]
    pm2 = ProjectManager(str(tmp_path))
    rows2 = pm2.list()["projects"]
    assert rows2[0]["id"] == first["id"]
    assert rows2[0]["pinned"] is True


def test_set_active_updates_last_active(tmp_path):
    pm = ProjectManager(str(tmp_path))
    first = pm.create("first", auto_start=False)
    second = pm.create("second", auto_start=False)
    old = first["last_active"]
    assert pm.set_active(first["id"])
    updated = pm.get(first["id"])
    assert pm.active_id == first["id"]
    assert updated["last_active"] >= old


def test_launcher_options_default_l4_scheduler_enabled(tmp_path):
    opts = load_options(str(tmp_path))
    assert opts["scheduler"] is True
    assert opts["permission_mode"] == "auto"


def test_project_start_options_persist_and_spawn_env(tmp_path, monkeypatch):
    pm = ProjectManager(str(tmp_path))
    project = pm.create(
        "configured",
        auto_start=False,
        options={
            "llm_no": 2,
            "permission_mode": "read-only",
            "project_root": str(tmp_path),
            "use_project_context": False,
            "autonomous_enabled": True,
        },
    )

    captured = {}

    class FakeProc:
        pid = 9876

    def fake_popen(cmd, cwd=None, env=None, stdout=None, stderr=None, creationflags=0):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProc()

    monkeypatch.setattr("launcher.project_manager.subprocess.Popen", fake_popen)
    pid = pm._spawn(project)

    assert pid == 9876
    assert captured["env"]["GA_LLM_NO"] == "2"
    assert captured["env"]["GA_PERMISSION_MODE"] == "read-only"
    assert captured["env"]["GA_PROJECT_ROOT"] == str(tmp_path)
    assert captured["env"]["GA_USE_PROJECT_CONTEXT"] == "0"
    assert captured["env"]["GA_AUTONOMOUS_ENABLED"] == "1"


def test_save_options_normalizes_values(tmp_path):
    opts = save_options(str(tmp_path), {"scheduler": "false", "llm_no": "3", "permission_mode": "bad"})
    assert opts["scheduler"] is False
    assert opts["llm_no"] == 3
    assert opts["permission_mode"] == "auto"
