# Native Strands Agents Integration

**Bring your Strands Agent. Get a full terminal UI. No FastAPI required.**

```bash
pip install 'gentui[strands]'
```

```python
from strands import Agent
from gentui import GentUI

GentUI.from_strands(Agent()).run()
```

That is the whole integration. The agent runs in your Python process; there is no server, no endpoint and no
second process. You get streaming chat, tool cards, reasoning, Approve / Reject, tables, charts and the event
inspector.

## Tool calling

Tools are ordinary Strands tools. Each call is drawn as a card with its name and arguments, a **running** state, and
then the tool's real output, or a red **failed** line if the tool raised.

```python
from strands import Agent, tool
from gentui import GentUI

@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

GentUI.from_strands(Agent(tools=[multiply])).run()
```

```text
> Calculate 125 * 42
  ◆ multiply(a=125.0, b=42.0)
    ⎿  5250.0
● 125 × 42 = 5250.
```

Several tool calls in one turn each get their own card. A tool request is never shown as finished until Strands
reports its result.

## Human approval

`approval_hook` makes chosen tools wait for the user. The agent pauses *before* the tool body runs.

```python
from gentui.adapters.strands import approval_hook

agent = Agent(tools=[list_files, delete_file])
agent.add_hook(approval_hook("delete_file"))     # no names = every tool
GentUI.from_strands(agent).run()
```

**Approve** runs the tool. **Reject** (or cancelling) never runs it: the model receives "The user rejected running
delete_file." as the tool's result and carries on. Anything other than an explicit `{"approved": true}` counts as a
rejection. `approval_hook(..., message="Really delete?")` changes the question; the message can also be a function
of the tool name and input.

Under the hood this is a Strands [interrupt](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/interrupts/):
nothing is faked. Your own hooks can call `event.interrupt(...)` too; Gentui shows them as Approve / Reject and
passes the answer back as `{"approved": bool}`.

While an approval is open, a new chat message is refused (the agent is paused mid-turn); answer it, or use `/new`.

## How it works

`StrandsAGUIAdapter` is a Gentui client, the same shape as the HTTP one. Instead of POSTing to a server it calls
`agent.stream_async()` and translates what comes back into AG-UI events. Everything after that is Gentui's normal
pipeline, so there is no Strands-specific UI.

| Strands | AG-UI event |
|---|---|
| invocation starts | `RUN_STARTED` |
| text delta | `TEXT_MESSAGE_START` (once), `TEXT_MESSAGE_CONTENT` |
| reasoning delta | `REASONING_START`, `REASONING_MESSAGE_START` / `_CONTENT` / `_END`, `REASONING_END` |
| tool use begins / input streams / block ends | `TOOL_CALL_START` / `TOOL_CALL_ARGS` / `TOOL_CALL_END` |
| tool result message | `TOOL_CALL_RESULT` (Strands' `success` / `error` status travels in `raw_event`) |
| agent paused by an interrupt | `RUN_FINISHED` with an interrupt outcome; the answer arrives as `resume` |
| invocation ends / raises | `RUN_FINISHED` / `RUN_ERROR` |

Only Strands' raw model events are used for text, reasoning and arguments, so nothing is shown twice. Message and
tool-call ids are stable, and anything still open when a run fails or stops is closed cleanly.

The dev pane (`d` or `/dev`) shows both sides: lines starting with `strands` are the Strands events, the JSON lines
are the AG-UI events produced from them.

**Multi-turn.** The agent keeps its own conversation, so each message continues it. `/new` clears the agent's
messages and starts over. An agent that already has history keeps it for the first chat.

## HTTP AG-UI or native?

| | Native (`GentUI.from_strands`) | HTTP (`gentui <url>`) |
|---|---|---|
| Server | none | you run one (FastAPI, `ag-ui-strands`, AgentCore...) |
| Where the agent runs | your process | wherever the server is |
| Setup | three lines | an endpoint and its hosting |
| Language | Python | any |
| Good for | prototyping, local tools, trying prompts | deployed agents, shared backends, non-Python agents |

Both go through the same AG-UI event pipeline, so the UI is identical. For a deployed agent keep using the HTTP
route (see [Backend contract](tool-contract.md) and [AgentCore Runtime](agentcore.md)).

## Tables and charts

Give the agent tools named `show_table` and `show_chart` with the arguments from the [Backend contract](tool-contract.md)
and Gentui draws them. The adapter forwards the calls unchanged.

## Supported, and not

**Supported:** streaming text; tool calls with arguments, running / done / failed; several tools per turn; sequential
tool use across model calls in one turn; reasoning from models that expose it; approval and rejection; tool calls made
by sub-agents (their chat text stays hidden); multi-turn; `/new`; errors; stopping a run; `--record` and replay;
the event inspector.

**Limitations:**

- No reasoning is shown unless the model returns it. Nothing is invented.
- A synchronous tool already running cannot be forced to stop when you stop a run; it may finish in the background.
  The agent's history is repaired so the next message works.
- Interrupts are answered as yes / no. Hooks that need free-form input are not supported yet.
- Only interrupts raised by tool hooks show next to the tool's card; other interrupts get a generic prompt.
- A tool's result is shown as text. Images and documents appear as `[image]` / `[document]`.
- Shared state (`STATE_SNAPSHOT`, the plan widget) is not produced; the agent's `state` is not mirrored.
- Multi-agent graphs and swarms are not wrapped; pass a single `Agent` (an agent that uses sub-agents as tools works).
- Built against `strands-agents` 1.57; the test suite runs on 1.59.

## Examples

[`examples/strands_native/`](https://github.com/rahrajlat/Gentui/tree/main/examples/strands_native) has three, built with
the Strands harness SDK (`create_harness`): `tool_call.py`, `tool_call_approval.py` and `chart.py`. They need
`pip install 'gentui[strands,harness,ollama]'` and a running, signed-in Ollama for their model. The tests need none of that: they drive
a real Strands agent with a scripted model.

`GentUI(adapter)` accepts any client that yields AG-UI events, so you can also write your own adapter.
