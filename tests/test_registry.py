from gentui.backend.registry import discover


def test_discover_finds_tools_and_subagents():
    names = {getattr(t, "tool_name", None) for t in discover()}
    assert {"run_command", "show_table", "get_system_info", "shell_agent", "explainer_agent"} <= names
    assert "propose_command" not in names  # private to the shell sub-agent
