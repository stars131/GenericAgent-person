from permissions import PermissionDecision, PermissionPolicy, ToolPermissionRequest, tool_metadata


def request(name, args=None, root="/tmp/project"):
    return ToolPermissionRequest(name, args or {}, root, root, tool_metadata(name))


def test_file_read_allowed_in_read_only():
    policy = PermissionPolicy(mode="read-only", interactive=False)
    decision = policy.decide(request("file_read", {"path": "a.txt"}))
    assert decision.decision == PermissionDecision.ALLOW


def test_file_write_denied_in_read_only():
    policy = PermissionPolicy(mode="read-only", interactive=False)
    decision = policy.decide(request("file_write", {"path": "a.txt"}))
    assert decision.decision == PermissionDecision.DENY


def test_ask_mode_non_interactive_denies_prompted_tools():
    policy = PermissionPolicy(mode="ask", interactive=False)
    decision = policy.decide(request("code_run", {"code": "print(1)"}))
    assert decision.decision == PermissionDecision.DENY


def test_session_allowlist_allows_tool():
    policy = PermissionPolicy(mode="ask", interactive=False)
    policy.allow_tool_for_session("code_run")
    decision = policy.decide(request("code_run", {"code": "print(1)"}))
    assert decision.decision == PermissionDecision.ALLOW
