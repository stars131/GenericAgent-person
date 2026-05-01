import argparse
import atexit
import ctypes
import importlib.util
import os
import random
import runpy
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from launcher.project_manager import ProjectManager
from launcher.shell_server import serve as serve_shell
from launcher.launch_config import load_options, project_options, save_options

WINDOW_WIDTH, WINDOW_HEIGHT, RIGHT_PADDING, TOP_PADDING = 820, 900, 0, 100

script_dir = os.path.dirname(os.path.abspath(__file__))
frontends_dir = os.path.join(script_dir, "frontends")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LAUNCHER_LOCK_PORT = 19736  # singleton lock for the local-UI launcher

window = None
pm = None


def find_free_port(lo=18400, hi=18499):
    """Free port for the shell HTTP server (separate range from project streamlits)."""
    ports = list(range(lo, hi + 1)); random.shuffle(ports)
    for port in ports:
        try:
            sock = socket.socket(); sock.bind(("127.0.0.1", port)); sock.close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"No free port in {lo}-{hi}")


def get_screen_width():
    try: return ctypes.windll.user32.GetSystemMetrics(0)
    except Exception: return 1920


def acquire_singleton():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try: s.bind(("127.0.0.1", LAUNCHER_LOCK_PORT)); s.listen(1); return s
    except OSError: return None


def get_feishu_startup_status():
    keys = {}
    for name in ("mykey.py", "mykey_local_override.py"):
        path = os.path.join(script_dir, name)
        if not os.path.exists(path): continue
        try: values = runpy.run_path(path)
        except Exception as exc: return False, f"config load failed: {name}: {exc}"
        keys.update({k: v for k, v in values.items() if not k.startswith("_")})
    app_id = str(keys.get("fs_app_id", "") or "").strip()
    app_secret = str(keys.get("fs_app_secret", "") or "").strip()
    if not app_id or not app_secret: return False, "fs_app_id/fs_app_secret not configured"
    if importlib.util.find_spec("lark_oapi") is None: return False, "lark_oapi not installed"
    return True, "configured"


def spawn_background(script_name):
    process = subprocess.Popen(
        [sys.executable, os.path.join(frontends_dir, script_name)],
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    atexit.register(process.kill)
    return process


def on_closing():
    """Called when the user clicks the close button."""
    if pm is None: return True
    running = [p for p in pm.list()["projects"] if p["running"]]
    if not running:
        return True
    msg = (f"有 {len(running)} 个项目正在后台运行：\n  "
           + "\n  ".join(p["name"] for p in running)
           + "\n\n确定 → 保留后台继续运行\n取消 → 全部停止后退出")
    keep = False
    try:
        keep = bool(window.evaluate_js(f"confirm({repr(msg)})"))
    except Exception as e:
        print(f"[Launch] close-confirm dialog failed, defaulting to keep: {e}")
        keep = True
    if keep:
        pm.detach_all()
        print(f"[Launch] {len(running)} project(s) detached, still running in background")
    else:
        pm.shutdown_all()
        print("[Launch] all projects stopped")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("port", nargs="?", default="0", help="(legacy, ignored)")
    parser.add_argument("--tg", action="store_true", help="Start Telegram bot")
    parser.add_argument("--qq", action="store_true", help="Start QQ bot")
    parser.set_defaults(feishu=False)
    parser.add_argument("--feishu", "--fs", dest="feishu", action="store_true", help="Start Feishu bot")
    parser.add_argument("--no-feishu", dest="feishu", action="store_false", help="Do not start Feishu bot")
    parser.add_argument("--wecom", action="store_true", help="Start WeCom bot")
    parser.add_argument("--dingtalk", "--dt", dest="dingtalk", action="store_true", help="Start DingTalk bot")
    parser.add_argument("--wechat", action="store_true", help="Start personal WeChat bot")
    parser.set_defaults(sched=None)
    parser.add_argument("--sched", dest="sched", action="store_true", help="Start task scheduler")
    parser.add_argument("--no-sched", dest="sched", action="store_false", help="Do not start task scheduler")
    parser.add_argument("--llm_no", type=int, default=None, help="LLM index")
    parser.add_argument("--qt", action="store_true", help="Start Qt launcher MVP")
    args = parser.parse_args()

    if args.qt:
        launch_options = load_options(script_dir)
        cli_overrides = {}
        for key in ("tg", "qq", "feishu", "wecom", "dingtalk", "wechat"):
            if getattr(args, key, False):
                cli_overrides[key] = True
        if args.sched is not None:
            cli_overrides["scheduler"] = args.sched
        if args.llm_no is not None:
            cli_overrides["llm_no"] = args.llm_no
        if cli_overrides:
            launch_options = save_options(script_dir, {**launch_options, **cli_overrides})
        # Spawn requested bots before handing off to Qt launcher (which manages
        # its own scheduler + project list internally).
        if launch_options.get("tg"): spawn_background("tgapp.py"); print("[Launch] Telegram Bot started")
        if launch_options.get("qq"): spawn_background("qqapp.py"); print("[Launch] QQ Bot started")
        feishu_ready, feishu_reason = get_feishu_startup_status()
        if launch_options.get("feishu") and feishu_ready:
            spawn_background("fsapp.py"); print("[Launch] Feishu Bot started")
        elif launch_options.get("feishu"):
            print(f"[Launch] Feishu Bot requested but not started: {feishu_reason}")
        if launch_options.get("wecom"): spawn_background("wecomapp.py"); print("[Launch] WeCom Bot started")
        if launch_options.get("dingtalk"): spawn_background("dingtalkapp.py"); print("[Launch] DingTalk Bot started")
        if launch_options.get("wechat"): spawn_background("wechatapp.py"); print("[Launch] WeChat Bot started")
        from launcher.qt_launcher import main as qt_main
        sys.exit(qt_main())

    launch_options = load_options(script_dir)
    cli_overrides = {}
    for key in ("tg", "qq", "feishu", "wecom", "dingtalk", "wechat"):
        if getattr(args, key, False):
            cli_overrides[key] = True
    if args.sched is not None:
        cli_overrides["scheduler"] = args.sched
    if args.llm_no is not None:
        cli_overrides["llm_no"] = args.llm_no
    if cli_overrides:
        launch_options = save_options(script_dir, {**launch_options, **cli_overrides})

    lock = acquire_singleton()
    if lock is None:
        print("[Launch] Another launcher is already running.")
        sys.exit(0)

    pm = ProjectManager(script_dir)

    # Bootstrap: create a default project on first run
    if not pm.projects:
        print("[Launch] First run — creating default project")
        active = pm.create("默认对话", auto_start=False)
        try:
            pm.update_options(active["id"], project_options(launch_options))
            pm.start(active["id"])
        except Exception as exc:
            print(f"[Launch] {exc}")
    else:
        # Reattach: any project whose pid+port still alive stays "running" automatically
        # (ProjectManager.is_running checks both). Auto-start the last active project
        # if it's not currently running.
        active = next((p for p in pm.projects if p["id"] == pm.active_id), None) or pm.projects[0]
        if not pm.is_running(active):
            print(f"[Launch] Auto-starting last active project: {active['name']}")
            try:
                pm.start(active["id"])
            except Exception as exc:
                print(f"[Launch] {exc}")

    shell_port = find_free_port()
    serve_shell(pm, shell_port, script_dir)
    print(f"[Launch] Shell on http://127.0.0.1:{shell_port}/")

    # Bots — kept tied to launcher lifetime (atexit kill), orthogonal to local projects
    if launch_options.get("tg"): spawn_background("tgapp.py"); print("[Launch] Telegram Bot started")
    if launch_options.get("qq"): spawn_background("qqapp.py"); print("[Launch] QQ Bot started")

    feishu_ready, feishu_reason = get_feishu_startup_status()
    if launch_options.get("feishu") and feishu_ready:
        spawn_background("fsapp.py"); print("[Launch] Feishu Bot started")
    elif launch_options.get("feishu"):
        print(f"[Launch] Feishu Bot requested but not started: {feishu_reason}")
    else:
        print("[Launch] Feishu Bot not enabled (use --feishu to start)")

    if launch_options.get("wecom"): spawn_background("wecomapp.py"); print("[Launch] WeCom Bot started")
    if launch_options.get("dingtalk"): spawn_background("dingtalkapp.py"); print("[Launch] DingTalk Bot started")
    if launch_options.get("wechat"): spawn_background("wechatapp.py"); print("[Launch] WeChat Bot started")

    if launch_options.get("scheduler", True):
        scheduler_proc = subprocess.Popen(
            [sys.executable, os.path.join(script_dir, "agentmain.py"),
             "--reflect", os.path.join(script_dir, "reflect", "scheduler.py"),
             "--llm_no", str(launch_options.get("llm_no", 0))],
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        atexit.register(scheduler_proc.kill)
        print("[Launch] Task Scheduler started")

    if os.name == "nt":
        screen_width = get_screen_width()
        x_pos = screen_width - WINDOW_WIDTH - RIGHT_PADDING
    else:
        x_pos = 100

    import webview
    window = webview.create_window(
        title="GenericAgent",
        url=f"http://127.0.0.1:{shell_port}/",
        width=WINDOW_WIDTH, height=WINDOW_HEIGHT,
        x=x_pos, y=TOP_PADDING,
        resizable=True, text_select=True,
    )
    window.events.closing += on_closing
    webview.start()
