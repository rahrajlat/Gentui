"""FastAPI app: POST /agent takes an AG-UI RunAgentInput and streams AG-UI events over SSE."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from ag_ui.core import EventType, RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from strands import Agent

from strands_backend.agui_adapter import run_to_agui
from strands_backend.approvals import PENDING_KEY, ProposalTracker, resume_prompt
from strands_backend.orchestrator import build_orchestrator
from strands_backend.tools.shell import record_approval

# Log every proposed / approved / executed command to the console and to .agent/commands.log
_log_file = Path(".agent/commands.log")
_log_file.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.WARNING)
shell_log = logging.getLogger("gentui")
shell_log.setLevel(logging.INFO)
_fh = logging.FileHandler(_log_file, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
shell_log.addHandler(_fh)
logging.getLogger("strands_harness.models").setLevel(logging.ERROR)  # noisy, harmless

# One agent per AG-UI thread_id, so each conversation keeps its history in memory.
# (Trade-off: lost on restart, one process only. Fine for the MVP.)
_agents: dict[str, Agent] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    # Memory extraction is background and turn-triggered: persist what is still pending.
    for agent in _agents.values():
        if getattr(agent, "memory_manager", None):
            try:
                await agent.memory_manager.flush()
            except Exception:  # noqa: BLE001 - never block shutdown on memory
                logging.getLogger("gentui").exception("memory flush failed")


app = FastAPI(title="Gentui agent", lifespan=lifespan)


def _agent_for(thread_id: str) -> Agent:
    if thread_id not in _agents:
        _agents[thread_id] = build_orchestrator()
    return _agents[thread_id]


def _last_user_text(body: RunAgentInput) -> str | None:
    for msg in reversed(body.messages):
        if msg.role == "user" and isinstance(msg.content, str):
            return msg.content
    return None


def _shared_state(agent: Agent) -> dict:
    """The state the TUI sees. Today: the plan written by the harness `todo_write` tool."""
    plan = agent.state.get("todos") or []
    return {"plan": [{"content": t["content"], "status": t["status"]} for t in plan]}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent")
async def agent_endpoint(body: RunAgentInput, request: Request) -> StreamingResponse:
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def stream():
        prompt = _last_user_text(body)
        if prompt is None and not body.resume:
            yield encoder.encode(RunErrorEvent(message="No user message in input"))
            return
        agent = _agent_for(body.thread_id)

        # AG-UI interrupts: `resume` answers the approval(s) the previous run ended on.
        if body.resume:
            try:
                prompt = resume_prompt(agent.state, body.resume)
            except KeyError as exc:
                yield encoder.encode(RunErrorEvent(message=f"Unknown or already answered interrupt {exc}"))
                return
        else:
            agent.state.set(PENDING_KEY, {})  # a fresh message abandons unanswered proposals

        # Button clicks arrive out-of-band in forwardedProps (the LLM never sees or sets this).
        approval = (body.forwarded_props or {}).get("approval")
        if isinstance(approval, dict) and approval.get("decision") == "approve":
            reason = record_approval(
                agent.state, str(approval.get("toolCallId", "")), str(approval.get("command", ""))
            )
            if reason:
                prompt += f"\n[System: the command was refused: {reason}. Do not run it.]"

        events = run_to_agui(
            agent.stream_async(prompt), body.thread_id, body.run_id,
            get_state=lambda: _shared_state(agent),
        )
        tracker = ProposalTracker()
        async for event in events:
            tracker.feed(event)
            if event.type == EventType.RUN_FINISHED:
                event = tracker.finish(event, agent.state)  # an unanswered proposal becomes an interrupt
            yield encoder.encode(event)

    return StreamingResponse(stream(), media_type=encoder.get_content_type())


def main() -> None:
    uvicorn.run("strands_backend.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
