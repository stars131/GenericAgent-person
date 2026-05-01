import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontends"))
from cli_commands import SharedCommandHandler


class Backend:
    history = []
    name = "test"


class Client:
    backend = Backend()


class Agent:
    is_running = False
    llm_no = 0
    llmclient = Client()
    llmclients = [llmclient]
    history = []
    permission_mode = "ask"
    project_root = "/tmp/project"
    project_context = None

    def abort(self):
        self.aborted = True

    def get_llm_name(self, b=None, model=False):
        return "TestSession/test"

    def list_llms(self):
        return [(0, "TestSession/test", True)]

    def next_llm(self, n=-1):
        self.llm_no = n


def test_help_handled():
    result = SharedCommandHandler(Agent()).handle("/help")
    assert result.handled
    assert "/status" in result.message


def test_status_includes_permission_and_project():
    result = SharedCommandHandler(Agent()).handle("/status")
    assert "Permission: ask" in result.message
    assert "Project: /tmp/project" in result.message


def test_session_sets_backend_value():
    agent = Agent()
    result = SharedCommandHandler(agent).handle("/session.temperature=0.5")
    assert result.handled
    assert agent.llmclient.backend.temperature == 0.5


def test_resume_returns_query_not_handled():
    result = SharedCommandHandler(Agent()).handle("/resume")
    assert not result.handled
    assert result.query
