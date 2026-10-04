"""Backend side of AG-UI interrupts: proposal -> interrupt outcome -> resume -> run_command prompt."""

import json

import pytest
from fastapi.testclient import TestClient

from strands_backend import app as backend
from strands_backend.tools.shell import APPROVED_KEY, PROPOSAL_OK


class State(dict):
    def set(self, k, v):
        self[k] = v


class FakeAgent:
    """Replays a scripted Strands stream and records the prompts it was given."""

    def __init__(self, command="ls -la", blocked=False):
        self.state, self.prompts = State(), []
        self.command, self.blocked = command, blocked

    async def stream_async(self, prompt):
        self.prompts.append(prompt)
        if "Approved" in prompt or "Rejected" in prompt or "refused" in prompt:
            return
        yield {"event": {"contentBlockStart": {"start": {"toolUse": {"name": "propose_command", "toolUseId": "c1"}}}}}
        yield {"event": {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(
            {"command": self.command, "explanation": "x", "risk": "safe"})}}}}}
        yield {"event": {"contentBlockStop": {}}}
        text = "BLOCKED: nope" if self.blocked else PROPOSAL_OK
        yield {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": "c1", "content": [{"text": text}]}}]}}


def post(client, thread, **body):
    payload = {"threadId": thread, "runId": "r", "state": {}, "messages": [], "tools": [], "context": [], "forwardedProps": {}, **body}
    r = client.post("/agent", json=payload)
    return [json.loads(l[5:]) for l in r.text.splitlines() if l.startswith("data:")]


def say(text):
    return {"messages": [{"id": "m", "role": "user", "content": text}]}


@pytest.fixture
def client():
    backend._agents.clear()
    with TestClient(backend.app) as c:
        yield c
    backend._agents.clear()


def last(events):
    return events[-1]


def test_proposal_ends_the_run_with_an_interrupt(client):
    backend._agents["t"] = FakeAgent()
    done = last(post(client, "t", **say("list files")))
    assert done["type"] == "RUN_FINISHED" and done["outcome"]["type"] == "interrupt"
    (i,) = done["outcome"]["interrupts"]
    assert i["id"] == "approve-c1" and i["reason"] == "tool_call" and i["toolCallId"] == "c1"
    assert i["responseSchema"]["required"] == ["approved"]
    # the command is remembered server-side, not trusted from the client later
    assert backend._agents["t"].state["pending_interrupts"]["approve-c1"]["command"] == "ls -la"


def test_blocked_proposal_raises_no_interrupt(client):
    backend._agents["t"] = FakeAgent(blocked=True)
    done = last(post(client, "t", **say("x")))
    assert done["type"] == "RUN_FINISHED" and "outcome" not in done


def test_approve_resume_records_server_side_command_and_prompts_run_command(client):
    agent = backend._agents["t"] = FakeAgent()
    post(client, "t", **say("list files"))
    events = post(client, "t", resume=[{"interruptId": "approve-c1", "status": "resolved", "payload": {"approved": True}}])
    assert last(events)["type"] == "RUN_FINISHED"
    assert agent.prompts[-1] == "Approved (approval_id=c1). Call run_command with this approval_id."
    assert agent.state[APPROVED_KEY] == {"c1": "ls -la"}  # the command WE recorded


def test_edited_command_is_used_but_rechecked(client):
    agent = backend._agents["t"] = FakeAgent()
    post(client, "t", **say("x"))
    post(client, "t", resume=[{"interruptId": "approve-c1", "status": "resolved",
                               "payload": {"approved": True, "command": "ls -l"}}])
    assert agent.state[APPROVED_KEY] == {"c1": "ls -l"}


def test_dangerous_edit_is_refused(client):
    agent = backend._agents["t"] = FakeAgent()
    post(client, "t", **say("x"))
    post(client, "t", resume=[{"interruptId": "approve-c1", "status": "resolved",
                               "payload": {"approved": True, "command": "rm -rf ~"}}])
    assert not agent.state.get(APPROVED_KEY)
    assert "refused" in agent.prompts[-1]


def test_cancel_and_not_approved_both_reject(client):
    for resume in (
        {"interruptId": "approve-c1", "status": "cancelled"},
        {"interruptId": "approve-c1", "status": "resolved", "payload": {"approved": False}},
        {"interruptId": "approve-c1", "status": "resolved"},
    ):
        agent = backend._agents["t"] = FakeAgent()
        post(client, "t", **say("x"))
        post(client, "t", resume=[resume])
        assert agent.prompts[-1] == "Rejected. Do not run it."
        assert not agent.state.get(APPROVED_KEY)


def test_unknown_or_replayed_interrupt_is_an_error(client):
    agent = backend._agents["t"] = FakeAgent()
    events = post(client, "t", resume=[{"interruptId": "nope", "status": "resolved", "payload": {"approved": True}}])
    assert last(events)["type"] == "RUN_ERROR"

    post(client, "t", **say("x"))
    ok = [{"interruptId": "approve-c1", "status": "resolved", "payload": {"approved": True}}]
    post(client, "t", resume=ok)
    assert last(post(client, "t", resume=ok))["type"] == "RUN_ERROR"  # one answer per interrupt
    assert len(agent.prompts) == 2  # the model was never run for the bad requests


def test_a_fresh_message_abandons_the_open_proposal(client):
    backend._agents["t"] = FakeAgent()
    post(client, "t", **say("x"))
    backend._agents["t"].command = "pwd"
    post(client, "t", **say("something else"))
    stale = [{"interruptId": "approve-c1", "status": "resolved", "payload": {"approved": True}}]
    # the second run raised a NEW interrupt with the same id for the new command
    assert backend._agents["t"].state["pending_interrupts"]["approve-c1"]["command"] == "pwd"
    assert last(post(client, "t", resume=stale))["type"] == "RUN_FINISHED"


def test_legacy_forwarded_props_handshake_still_works(client):
    agent = backend._agents["t"] = FakeAgent()
    post(client, "t", **say("Approved (approval_id=c1). Call run_command with this approval_id."),
         forwardedProps={"approval": {"decision": "approve", "command": "ls", "toolCallId": "c1"}})
    assert agent.state[APPROVED_KEY] == {"c1": "ls"}


def test_a_failed_proposal_raises_no_interrupt_only_the_retry_does(client):
    """The model first sent an invalid call (tool error), then retried successfully."""

    class Retrying(FakeAgent):
        async def stream_async(self, prompt):
            self.prompts.append(prompt)
            if "Approved" in prompt:
                return
            for call_id, risk_ok in (("bad", False), ("good", True)):
                yield {"event": {"contentBlockStart": {"start": {"toolUse": {"name": "propose_command", "toolUseId": call_id}}}}}
                yield {"event": {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(
                    {"command": "date", "explanation": "x", "risk": "safe" if risk_ok else "read-only"})}}}}}
                yield {"event": {"contentBlockStop": {}}}
                text = PROPOSAL_OK if risk_ok else "Error: Validation failed for input parameters: 1 validation error"
                yield {"message": {"role": "user", "content": [{"toolResult": {"toolUseId": call_id, "content": [{"text": text}]}}]}}

    backend._agents["t"] = Retrying()
    done = post(client, "t", **say("what is the date ?"))[-1]
    interrupts = done["outcome"]["interrupts"]
    assert [i["toolCallId"] for i in interrupts] == ["good"]  # exactly one, for the valid proposal


def test_risk_words_are_normalised_not_rejected():
    from strands_backend.tools.shell import normalize_risk

    assert normalize_risk("read-only") == "safe" and normalize_risk("READONLY") == "safe"
    assert normalize_risk("high") == "dangerous" and normalize_risk("medium") == "caution"
    assert normalize_risk("???") == "caution"  # unknown stays cautious
