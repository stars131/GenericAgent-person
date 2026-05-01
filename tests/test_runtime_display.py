from agentmain import GeneraticAgent, format_duration


def test_format_duration_seconds():
    assert format_duration(3.24) == "3.2s"


def test_format_duration_minutes():
    assert format_duration(65.0) == "1m 05s"


def test_non_interactive_config_does_not_enable_cli_cwd(tmp_path):
    agent = GeneraticAgent()
    agent.configure_cli(permission_mode="read-only", project_root=tmp_path, interactive=False)
    assert agent.cli_mode is False
    assert agent.project_root == str(tmp_path.resolve())
