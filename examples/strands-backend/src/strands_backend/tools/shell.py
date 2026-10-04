"""Shell tools.

  propose_command  -> only RECORDS a proposal (the TUI renders it as a command widget).
                      Private to the shell sub-agent: NOT registered on the orchestrator.
  run_command      -> executes, but ONLY a command the human approved in the TUI.

Approvals travel out-of-band (AG-UI `forwardedProps`, see app.py) and are stored in the
orchestrator's `agent.state` as {approval_id: command}. The LLM only ever passes the
approval_id, so it can neither approve its own commands nor alter an approved one
(models are unreliable at re-typing shell quoting and escapes).
"""

import json
import logging
import platform
import subprocess
from typing import Any

from strands import ToolContext, tool

from strands_backend.config import get_settings
from strands_backend.registry import register_tool
from strands_backend.tools.shell_safety import check_command

log = logging.getLogger("gentui.shell")

APPROVED_KEY = "approved_commands"
PROPOSAL_OK = "Proposal shown to the user. It has NOT been run. Stop and wait for the user's decision."

# Models say "read-only", "low", "high"...; a strict enum made the call fail and the model retried,
# producing a second (phantom) proposal. Normalise instead of rejecting.
_RISK_WORDS = {
    "safe": "safe", "read-only": "safe", "readonly": "safe", "read_only": "safe", "low": "safe", "harmless": "safe",
    "caution": "caution", "medium": "caution", "moderate": "caution", "modifies": "caution", "write": "caution",
    "dangerous": "dangerous", "danger": "dangerous", "high": "dangerous", "destructive": "dangerous",
    "critical": "dangerous", "irreversible": "dangerous",
}


def normalize_risk(risk: str) -> str:
    return _RISK_WORDS.get(str(risk).strip().lower(), "caution")  # unknown -> be cautious


def detect_shell() -> str:
    """Which shell syntax commands must use on this machine."""
    return "PowerShell" if platform.system() == "Windows" else "bash"


def record_approval(state: Any, approval_id: str, command: str) -> str | None:
    """Store a human approval. Returns a refusal reason if the safety policy forbids it."""
    reason = check_command(command)
    if reason:
        log.warning("APPROVAL REFUSED (%s): %s", reason, command)
        return reason
    state.set(APPROVED_KEY, {**(state.get(APPROVED_KEY) or {}), approval_id: command})
    log.info("APPROVED by user [%s]: %s", approval_id, command)
    return None


@tool
def propose_command(
    command: str,
    explanation: str,
    risk: str,
) -> str:
    """Propose ONE shell command for the user to approve. This does NOT run the command.

    Args:
        command: The exact command line, in the syntax of the user's shell.
        explanation: One sentence saying what the command does.
        risk: One of "safe" (read-only), "caution" (changes files or settings) or "dangerous" (destructive or irreversible).
    """
    risk = normalize_risk(risk)
    log.info("PROPOSED [%s] %s", risk, command)
    reason = check_command(command)
    if reason:
        return f"BLOCKED: {reason}. Do not retry it; propose a safer alternative or explain."
    return PROPOSAL_OK


@register_tool
@tool(context=True)
def run_command(approval_id: str, tool_context: ToolContext) -> str:
    """Run a shell command that the user has ALREADY approved.

    Args:
        approval_id: The approval_id given in the user's approval message.
    """
    state = tool_context.agent.state
    approved: dict[str, str] = dict(state.get(APPROVED_KEY) or {})
    command = approved.pop(approval_id, None)  # one approval = one run
    if command is None:
        log.warning("REFUSED (unknown approval_id): %s", approval_id)
        return "REFUSED: no approved command for this approval_id. Propose one first."
    state.set(APPROVED_KEY, approved)

    reason = check_command(command)  # belt and braces: re-check at execution time
    if reason:
        return f"REFUSED: {reason}"

    s = get_settings()
    if platform.system() == "Windows":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-c", command]
    log.info("EXECUTING in %s: %s", s.shell_cwd, command)
    result: dict[str, Any] = {"command": command, "exit_code": None, "timed_out": False, "truncated": False, "output": ""}
    try:
        p = subprocess.run(
            argv, cwd=s.shell_cwd, capture_output=True, text=True, errors="replace",
            stdin=subprocess.DEVNULL, timeout=s.shell_timeout,
        )
        out, result["exit_code"] = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        result["timed_out"] = True
    except OSError as e:
        out = f"could not start shell: {e}"
    if len(out) > s.shell_max_output:
        out, result["truncated"] = out[: s.shell_max_output], True
    result["output"] = out
    log.info("FINISHED exit=%s timed_out=%s", result["exit_code"], result["timed_out"])
    return json.dumps(result)
