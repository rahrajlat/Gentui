import pytest

from strands_backend.tools.shell_safety import check_command

BLOCKED = [
    "rm -rf /", "rm -rf /*", "sudo rm -rf ~", "rm -fr $HOME", "rm -rf * ", "rm -rf --no-preserve-root /",
    "mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/sda", "format C:", "Format-Volume -DriveLetter D",
    "shutdown -h now", "sudo reboot", "Stop-Computer", "Restart-Computer -Force",
    "Remove-Item -Recurse -Force C:\\", "Remove-Item C:\\Users -Recurse", "rd /s /q C:\\",
    "reg add HKLM\\Software\\X /v a", "reg delete HKCU\\Software\\Y", "Set-ItemProperty -Path HKLM:\\SOFTWARE\\X -Name a",
    ":(){ :|:& };:", "chmod -R 777 /", "vim file.txt", "less /var/log/syslog", "top", "",
]
ALLOWED = [
    "ls -la", "du -sh .", "rm -rf ./build", "rm -rf /tmp/foo", "rm old.txt", "find . -name '*.py' | head",
    "Get-ChildItem -Recurse", "Remove-Item -Recurse .\\build", "git status", "echo shutdown", "cat README.md",
]


@pytest.mark.parametrize("cmd", BLOCKED)
def test_blocked(cmd):
    assert check_command(cmd), f"should be blocked: {cmd!r}"


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd):
    assert check_command(cmd) is None, f"should be allowed: {cmd!r}"


def test_run_command_only_runs_approved_ids_once(tmp_path, monkeypatch):
    """The LLM only passes an approval_id: unknown ids are refused, approved ones run exactly once."""
    import json

    from strands.agent.state import AgentState

    from strands_backend.tools import shell

    monkeypatch.setenv("GENTUI_SHELL_CWD", str(tmp_path))
    state = AgentState()

    class Agent:
        pass

    class Ctx:  # the only ToolContext surface run_command uses
        agent = Agent()

    Ctx.agent.state = state
    run = shell.run_command.__wrapped__  # the plain function behind the @tool decorator

    assert run("nope", Ctx).startswith("REFUSED")
    assert shell.record_approval(state, "a1", "echo hello") is None
    assert shell.record_approval(state, "a2", "rm -rf /") is not None  # policy beats approval

    result = json.loads(run("a1", Ctx))
    assert result["exit_code"] == 0 and "hello" in result["output"] and result["command"] == "echo hello"
    assert run("a1", Ctx).startswith("REFUSED")  # consumed: one approval = one run
    assert run("a2", Ctx).startswith("REFUSED")  # never stored
