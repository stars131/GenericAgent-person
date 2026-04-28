"""Project lifecycle: persistent metadata + streamlit subprocess management."""
import json, os, random, secrets, socket, subprocess, sys, threading, time
from datetime import datetime

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    import psutil

    def _pid_alive(pid):
        try:
            p = psutil.Process(pid)
            return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        except Exception:
            return False
except ImportError:
    if os.name == "nt":
        def _pid_alive(pid):
            try:
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=CREATE_NO_WINDOW,
                )
                return f" {pid} " in r.stdout
            except Exception:
                return False
    else:
        def _pid_alive(pid):
            try:
                os.kill(pid, 0)
                return True
            except Exception:
                return False


def _port_alive(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def _port_free(port):
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", port))
        s.close()
        return True
    except OSError:
        return False


class ProjectManager:
    PORT_LO, PORT_HI = 18501, 18599

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.frontends_dir = os.path.join(base_dir, "frontends")
        self.json_path = os.path.join(base_dir, "temp", "projects.json")
        os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
        self.lock = threading.Lock()
        self._procs = {}  # id -> Popen (only for processes we spawned this session)
        self._load()

    def _load(self):
        if os.path.isfile(self.json_path):
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.projects = data.get("projects", [])
                for project in self.projects:
                    project.setdefault("last_error", "")
                self.active_id = data.get("active_id")
                return
            except Exception as e:
                print(f"[ProjectManager] load failed, starting fresh: {e}")
        self.projects = []
        self.active_id = None

    def _save(self):
        tmp = self.json_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"projects": self.projects, "active_id": self.active_id}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.json_path)

    def _by_id(self, pid):
        for p in self.projects:
            if p["id"] == pid:
                return p
        return None

    def get(self, project_id):
        with self.lock:
            project = self._by_id(project_id)
            return {**project, "running": self.is_running(project)} if project else None

    def _used_ports(self):
        return {p["port"] for p in self.projects if p.get("port")}

    def _alloc_port(self):
        used = self._used_ports()
        ports = list(range(self.PORT_LO, self.PORT_HI + 1))
        random.shuffle(ports)
        for port in ports:
            if port in used:
                continue
            if _port_free(port):
                return port
        raise RuntimeError("no free port in range")

    def _gen_id(self):
        existing = {p["id"] for p in self.projects}
        for _ in range(20):
            pid = "p_" + secrets.token_hex(4)
            if pid not in existing:
                return pid
        raise RuntimeError("id collision")

    def is_running(self, project):
        pid = project.get("pid")
        port = project.get("port")
        if not pid or not port:
            return False
        return _pid_alive(pid) and _port_alive(port)

    def list(self):
        with self.lock:
            out = []
            for p in self.projects:
                out.append({**p, "running": self.is_running(p)})
            return {"projects": out, "active_id": self.active_id}

    def create(self, name, auto_start=True):
        with self.lock:
            name = (name or "").strip() or "新对话"
            project = {
                "id": self._gen_id(),
                "name": name,
                "port": self._alloc_port(),
                "pid": None,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "last_active": datetime.now().isoformat(timespec="seconds"),
                "llm_no": 0,
                "last_error": "",
            }
            self.projects.append(project)
            self.active_id = project["id"]
            self._save()
        if auto_start:
            self.start(project["id"])
        return project

    def _read_log_tail(self, log_path, max_chars=1200):
        if not log_path or not os.path.exists(log_path):
            return ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[-max_chars:].strip()
        except Exception:
            return ""

    def _spawn(self, project):
        env = os.environ.copy()
        env["GA_PROJECT_NAME"] = project["name"]
        env["GA_PROJECT_ID"] = project["id"]
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            os.path.join(self.frontends_dir, "stapp.py"),
            "--global.developmentMode",
            "false",
            "--server.port",
            str(project["port"]),
            "--server.address",
            "localhost",
            "--server.headless",
            "true",
        ]
        log_dir = os.path.join(self.base_dir, "temp", "project_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{project['id']}.log")
        project["log_path"] = log_path
        log_f = open(log_path, "a", encoding="utf-8", errors="replace")
        log_f.write(f"\n\n=== spawn {datetime.now().isoformat()} ===\n")
        log_f.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=self.base_dir,
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self._procs[project["id"]] = proc
        return proc.pid

    def start(self, project_id):
        with self.lock:
            project = self._by_id(project_id)
            if not project:
                return False
            if self.is_running(project):
                return True
            if not _port_free(project["port"]) and not _port_alive(project["port"]):
                project["port"] = self._alloc_port()
            elif not _port_free(project["port"]) and _port_alive(project["port"]):
                project["port"] = self._alloc_port()
            project["last_error"] = ""
            project["pid"] = self._spawn(project)
            project["last_active"] = datetime.now().isoformat(timespec="seconds")
            self._save()
        deadline = time.time() + 15
        while time.time() < deadline:
            if _port_alive(project["port"]):
                with self.lock:
                    project["last_error"] = ""
                    self._save()
                return True
            proc = self._procs.get(project_id)
            if proc is not None and proc.poll() is not None:
                break
            if project.get("pid") and not _pid_alive(project["pid"]):
                break
            time.sleep(0.3)
        tail = self._read_log_tail(project.get("log_path"))
        reason = f"Project '{project['name']}' failed to start on port {project['port']}"
        if tail:
            last_line = tail.splitlines()[-1].strip()
            if last_line:
                reason = f"{reason}: {last_line}"
        self._procs.pop(project_id, None)
        with self.lock:
            project["pid"] = None
            project["last_error"] = reason
            self._save()
        raise RuntimeError(reason)

    def stop(self, project_id, timeout=5):
        with self.lock:
            project = self._by_id(project_id)
            if not project:
                return False
            pid = project.get("pid")
        if not pid:
            return True
        proc = self._procs.get(project_id)
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                if _pid_alive(pid):
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True,
                            creationflags=CREATE_NO_WINDOW,
                        )
                    else:
                        try:
                            os.kill(pid, 15)
                        except Exception:
                            pass
        except Exception as e:
            print(f"[ProjectManager] stop {project_id} error: {e}")
        self._procs.pop(project_id, None)
        with self.lock:
            project["pid"] = None
            project["last_error"] = ""
            self._save()
        return True

    def rename(self, project_id, name):
        name = (name or "").strip()
        if not name:
            return False
        with self.lock:
            project = self._by_id(project_id)
            if not project:
                return False
            project["name"] = name
            self._save()
        return True

    def delete(self, project_id, stop_first=True):
        if stop_first:
            self.stop(project_id)
        with self.lock:
            self.projects = [p for p in self.projects if p["id"] != project_id]
            if self.active_id == project_id:
                self.active_id = self.projects[0]["id"] if self.projects else None
            self._save()
        return True

    def set_active(self, project_id):
        with self.lock:
            if not self._by_id(project_id):
                return False
            self.active_id = project_id
            self._save()
        return True

    def shutdown_all(self):
        for p in list(self.projects):
            self.stop(p["id"])

    def detach_all(self):
        self._procs.clear()
