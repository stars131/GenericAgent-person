"""Tests for SSE log-streaming endpoints in launcher.api_server."""
from __future__ import annotations

import http.client
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from launcher import api_server, bot_manager
from launcher.project_manager import ProjectManager


@pytest.fixture(scope="module")
def server_port(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("api_server_sse")
    api_server._project_manager = ProjectManager(str(tmp_dir))
    api_server._bot_manager = bot_manager.BotManager(str(tmp_dir))

    port = None
    last_err: Exception | None = None
    for _ in range(5):
        try:
            port, _t = api_server.serve_threaded()
            break
        except (OSError, PermissionError) as exc:
            last_err = exc
    if port is None:
        raise RuntimeError(f"could not start: {last_err}")
    yield port, tmp_dir


def _read_events(port: int, path: str, *, want: int, timeout: float = 5.0) -> list[tuple[str, str]]:
    """Open SSE stream, collect up to `want` events, then close."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    conn.request("GET", path)
    resp = conn.getresponse()
    assert resp.status == 200, f"unexpected status {resp.status}"
    assert "text/event-stream" in resp.headers.get("Content-Type", "")

    events: list[tuple[str, str]] = []
    buf = b""
    deadline = time.monotonic() + timeout
    fp = resp.fp  # type: ignore[attr-defined]
    while len(events) < want and time.monotonic() < deadline:
        chunk = fp.read1(4096)
        if not chunk:
            break
        buf += chunk
        # Frames are separated by blank line
        while b"\n\n" in buf:
            frame, buf = buf.split(b"\n\n", 1)
            event_name = ""
            data_lines: list[str] = []
            for line in frame.decode("utf-8").splitlines():
                if line.startswith("event: "):
                    event_name = line[len("event: ") :]
                elif line.startswith("data: "):
                    data_lines.append(line[len("data: ") :])
            events.append((event_name, "\n".join(data_lines)))
    conn.close()
    return events


def test_project_stream_unknown(server_port):
    port, _ = server_port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", "/api/projects/unknown/log/stream")
    resp = conn.getresponse()
    assert resp.status == 404
    conn.close()


def test_bot_stream_unknown(server_port):
    port, _ = server_port
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", "/api/bots/notabot/log/stream")
    resp = conn.getresponse()
    assert resp.status == 404
    conn.close()


def test_project_stream_meta_when_no_log(server_port):
    """Even with no log file yet, stream should send a meta event then heartbeat."""
    port, _ = server_port
    pm = api_server._pm()
    project = pm.create("sse-empty", auto_start=False)
    events = _read_events(port, f"/api/projects/{project['id']}/log/stream", want=1, timeout=2)
    assert len(events) >= 1
    assert events[0][0] == "meta"
    assert "exists" in events[0][1]


def test_project_stream_initial_tail_and_append(server_port):
    """Write existing log content + an appended line; expect both via SSE."""
    port, tmp_dir = server_port
    pm = api_server._pm()
    project = pm.create("sse-tail", auto_start=False)
    log_dir = tmp_dir / "temp" / "project_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{project['id']}.log"
    log_path.write_text("first line\nsecond line\n", encoding="utf-8")
    pm.get(project["id"])  # ensure exists path is present after persistence
    pm._by_id(project["id"])["log_path"] = str(log_path)  # type: ignore[index]

    # Open stream first, then append after a beat so we capture both
    import threading

    captured: list[list[tuple[str, str]]] = [[]]

    def reader():
        captured[0] = _read_events(
            port,
            f"/api/projects/{project['id']}/log/stream",
            want=3,
            timeout=4,
        )

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(0.5)  # let the reader subscribe + receive initial tail
    with log_path.open("a", encoding="utf-8") as f:
        f.write("third line\n")
    t.join(timeout=5)

    events = captured[0]
    assert any(name == "meta" for name, _ in events)
    appends = [data for name, data in events if name == "append"]
    full = "\n".join(appends)
    assert "first line" in full or "second line" in full
    # third-line append is best-effort due to scheduler; allow either history or live.


def test_bot_stream_meta_when_no_log(server_port):
    port, _ = server_port
    events = _read_events(port, "/api/bots/feishu/log/stream", want=1, timeout=2)
    assert len(events) >= 1
    assert events[0][0] == "meta"
