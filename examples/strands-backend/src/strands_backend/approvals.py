"""AG-UI interrupts for command approval.

    run 1   model calls propose_command -> the run ends with
            RUN_FINISHED{outcome: interrupt, interrupts: [{id, reason: "tool_call", toolCallId, ...}]}
            and the proposed command is remembered HERE, server-side, keyed by the interrupt id.
    run 2   the client posts `resume: [{interruptId, status, payload}]` on the same thread.
            We look the command up ourselves (the client only says yes/no, or sends an edit),
            record the approval, and give the model the usual "Approved (approval_id=...)" prompt.

The interrupt is raised at the AG-UI boundary, not inside the Strands sub-agent, so the model-facing
flow (propose -> turn ends -> run_command(approval_id)) is unchanged.
"""

import json
from typing import Any

from ag_ui.core import (
    BaseEvent,
    EventType,
    Interrupt,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
)

from strands_backend.tools.shell import PROPOSAL_OK, record_approval

PENDING_KEY = "pending_interrupts"  # agent.state: {interrupt_id: {"command", "tool_call_id"}}
PROPOSE_TOOL = "propose_command"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "command": {"type": "string", "description": "only when the user edited the command"},
    },
    "required": ["approved"],
}


class ProposalTracker:
    """Watches one run's AG-UI events; turns the final RUN_FINISHED into an interrupt if the model
    proposed a command that was not blocked."""

    def __init__(self) -> None:
        self._args: dict[str, str] = {}  # propose_command tool_call_id -> raw JSON args so far

    def feed(self, event: BaseEvent) -> None:
        t = event.type
        if t == EventType.TOOL_CALL_START and event.tool_call_name == PROPOSE_TOOL:
            self._args[event.tool_call_id] = ""
        elif t == EventType.TOOL_CALL_ARGS and event.tool_call_id in self._args:
            self._args[event.tool_call_id] += event.delta
        elif t == EventType.TOOL_CALL_RESULT and event.tool_call_id in self._args:
            if not event.content.startswith(PROPOSAL_OK):
                # BLOCKED by the safety policy, or the call itself failed (e.g. a validation
                # error the model will retry): there is nothing to approve.
                del self._args[event.tool_call_id]

    def finish(self, event: RunFinishedEvent, state: Any) -> RunFinishedEvent:
        """Return `event` unchanged, or a RUN_FINISHED carrying the interrupt(s)."""
        interrupts: list[Interrupt] = []
        pending: dict[str, dict[str, str]] = {}
        for call_id, raw in self._args.items():
            try:
                command = str(json.loads(raw).get("command") or "").strip()
            except (json.JSONDecodeError, AttributeError):
                continue
            if not command:
                continue
            interrupt_id = f"approve-{call_id}"
            pending[interrupt_id] = {"command": command, "tool_call_id": call_id}
            interrupts.append(
                Interrupt(
                    id=interrupt_id,
                    reason="tool_call",
                    message=f"Run this command?  {command}",
                    tool_call_id=call_id,
                    response_schema=RESPONSE_SCHEMA,
                )
            )
        if not interrupts:
            return event
        state.set(PENDING_KEY, pending)
        return RunFinishedEvent(
            thread_id=event.thread_id,
            run_id=event.run_id,
            outcome=RunFinishedInterruptOutcome(interrupts=interrupts),
        )


def resume_prompt(state: Any, resume: list[Any]) -> str:
    """Answer the open interrupts and return the prompt to give the model.

    Raises KeyError for an interrupt id we never raised (or already answered)."""
    pending: dict[str, dict[str, str]] = dict(state.get(PENDING_KEY) or {})
    lines: list[str] = []
    for entry in resume:
        info = pending.pop(entry.interrupt_id)  # KeyError -> unknown / already answered
        payload = entry.payload if isinstance(entry.payload, dict) else {}
        if entry.status == "resolved" and payload.get("approved") is True:
            # The command we recorded; the client only sends one back if the user edited it.
            command = str(payload.get("command") or info["command"])
            reason = record_approval(state, info["tool_call_id"], command)
            if reason:
                lines.append(f"[System: the command was refused: {reason}. Do not run it.]")
            else:
                lines.append(
                    f"Approved (approval_id={info['tool_call_id']}). Call run_command with this approval_id."
                )
        else:
            lines.append("Rejected. Do not run it.")
    state.set(PENDING_KEY, pending)
    return "\n".join(lines)
