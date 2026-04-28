import os
import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTENDS_DIR = os.path.join(REPO_DIR, "frontends")
TEST_TEMP_ROOT = os.path.join(REPO_DIR, "temp")
os.makedirs(TEST_TEMP_ROOT, exist_ok=True)
if FRONTENDS_DIR not in sys.path:
    sys.path.insert(0, FRONTENDS_DIR)

import chatapp_common
import continue_cmd
import project_context
from launcher.project_manager import ProjectManager


@contextmanager
def workspace_tmpdir(prefix):
    path = os.path.join(TEST_TEMP_ROOT, f"{prefix}_{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_native_log(path, user_text, summary_text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = (
        "=== Prompt === 2026-04-27 00:00:00\n"
        f'{{"role": "user", "content": [{{"type": "text", "text": "{user_text}"}}]}}\n\n'
        "=== Response === 2026-04-27 00:00:01\n"
        f'[{{"type": "text", "text": "<summary>{summary_text}</summary>\\nDone"}}]\n\n'
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class _ExitedProc:
    def poll(self):
        return 1


class TestProjectScopedLogs(unittest.TestCase):
    def test_project_context_uses_project_subdir(self):
        with workspace_tmpdir("project_ctx") as td:
            with patch.dict(os.environ, {"GA_PROJECT_ID": "p_demo"}, clear=False):
                path = project_context.get_model_response_log_path(pid=321, base_dir=td)
            self.assertEqual(path, os.path.join(td, "temp", "model_responses", "p_demo", "model_responses_321.txt"))

    def test_continue_lists_only_current_project_logs(self):
        with workspace_tmpdir("project_continue") as td:
            p1_globs = project_context.get_model_response_globs(base_dir=td, project_id="p1")
            p2_dir = project_context.get_model_responses_dir(base_dir=td, project_id="p2")
            _write_native_log(os.path.join(project_context.get_model_responses_dir(base_dir=td, project_id="p1"), "model_responses_101.txt"), "project one", "sum one")
            _write_native_log(os.path.join(p2_dir, "model_responses_202.txt"), "project two", "sum two")
            with patch.object(continue_cmd.project_context, "get_model_response_globs", return_value=p1_globs):
                sessions = continue_cmd.list_sessions()
            self.assertEqual(len(sessions), 1)
            self.assertIn(os.path.join("p1", "model_responses_101.txt"), sessions[0][0])

    def test_restore_uses_only_current_project_logs(self):
        with workspace_tmpdir("project_restore") as td:
            p1_dir = project_context.get_model_responses_dir(base_dir=td, project_id="p1")
            p2_dir = project_context.get_model_responses_dir(base_dir=td, project_id="p2")
            p1_path = os.path.join(p1_dir, "model_responses_101.txt")
            p2_path = os.path.join(p2_dir, "model_responses_202.txt")
            _write_native_log(p1_path, "project one", "sum one")
            _write_native_log(p2_path, "project two", "sum two")
            os.utime(p2_path, None)
            with patch.object(chatapp_common.project_context, "get_model_response_globs", return_value=project_context.get_model_response_globs(base_dir=td, project_id="p1")):
                restored_info, err = chatapp_common.format_restore()
            self.assertIsNone(err)
            self.assertIsNotNone(restored_info)
            _, fname, _ = restored_info
            self.assertEqual(fname, os.path.basename(p1_path))


class TestProjectManagerStartFailures(unittest.TestCase):
    def test_start_records_error_when_process_exits_before_port_is_ready(self):
        with workspace_tmpdir("project_manager") as td:
            os.makedirs(os.path.join(td, "frontends"), exist_ok=True)
            pm = ProjectManager(td)
            project = pm.create("demo", auto_start=False)

            def fake_spawn(proj):
                log_dir = os.path.join(td, "temp", "project_logs")
                os.makedirs(log_dir, exist_ok=True)
                log_path = os.path.join(log_dir, f"{proj['id']}.log")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("Traceback\nModuleNotFoundError: No module named 'streamlit'\n")
                proj["log_path"] = log_path
                pm._procs[proj["id"]] = _ExitedProc()
                return 4321

            with patch.object(pm, "_spawn", side_effect=fake_spawn), \
                 patch("launcher.project_manager._port_alive", return_value=False), \
                 patch("launcher.project_manager._pid_alive", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "streamlit"):
                    pm.start(project["id"])

            current = pm.get(project["id"])
            self.assertIsNotNone(current)
            self.assertIsNone(current["pid"])
            self.assertIn("streamlit", current["last_error"])


if __name__ == "__main__":
    unittest.main()
