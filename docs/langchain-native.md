# Native LangChain Integration

**Bring your LangChain / LangGraph agent. Get a full terminal UI. No server required.**

```bash
pip install 'gentui[langchain]'
```

```python
from langchain.agents import create_agent
from gentui import GentUI

agent = create_agent("anthropic:claude-sonnet-4-5", tools=[])
GentUI.from_langchain(agent).run()
```

The agent runs in your Python process; there is no server, no endpoint and no second process. It works with any
compiled LangGraph graph (what `create_agent` and `langgraph.prebuilt.create_react_agent` return). You get streaming
chat, tool cards, reasoning, Approve / Reject, tables, charts and the event inspector. It is the same experience as
[native Strands agents](strands-native.md).

## Tool calling

Tools are ordinary LangChain tools. Each call is drawn as a card with its name and arguments, a **running** state, and
then the tool's real output, or a red **failed** line if the tool errored.

```python
from langchain.agents import create_agent
from langchain_core.tools import tool
from gentui import GentUI

@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b

GentUI.from_langchain(create_agent(model, tools=[multiply])).run()
```

## Showing the model's thinking

Gentui shows the thinking that LangChain returns, but most chat models only return it when you ask. With Ollama, pass
`reasoning=True`; without it, `langchain-ollama` leaves the thinking out (or mixes it into the answer):

```python
model = init_chat_model("ollama:gpt-oss:20b", reasoning=True)    # or ChatOllama(model=..., reasoning=True)
```

Other providers have their own switch (for example extended thinking on Anthropic models). Gentui reads thinking blocks in
the message content and `additional_kwargs["reasoning_content"]`.

## Human approval

`approval_middleware` makes chosen tools wait for the user. The graph pauses *before* the tool body runs.

```python
from gentui.adapters.langchain import approval_middleware

agent = create_agent(model, tools=[list_files, delete_file],
                     middleware=[approval_middleware("delete_file")])   # no names = every tool
GentUI.from_langchain(agent).run()
```

**Approve** runs the tool. **Reject** (or cancelling) never runs it: the model receives "The user rejected running
delete_file." as the tool's result (flagged as an error) and carries on. Anything other than an explicit
`{"approved": true}` counts as a rejection. `approval_middleware(..., message="Really delete?")` changes the question;
the message can also be a function of the tool name and input.

Under the hood this is LangGraph's [`interrupt()`](https://docs.langchain.com/oss/python/langgraph/interrupts): your own
code can call it too. Gentui shows it as Approve / Reject and resumes the graph with `Command(resume={"approved": bool})`.
While an approval is open, a new chat message is refused; answer it, or use `/new`.

## How it works

`LangChainAGUIAdapter` is a Gentui client, the same shape as the HTTP one. It calls
`agent.astream_events(..., version="v2")` and translates the events into AG-UI events.

| LangChain | AG-UI event |
|---|---|
| invocation starts | `RUN_STARTED` |
| chat model text chunk | `TEXT_MESSAGE_START` (once), `TEXT_MESSAGE_CONTENT` |
| thinking blocks / `reasoning_content` | `REASONING_START`, `REASONING_MESSAGE_*`, `REASONING_END` |
| tool call chunks | `TOOL_CALL_START` / `TOOL_CALL_ARGS` / `TOOL_CALL_END` |
| `ToolMessage` | `TOOL_CALL_RESULT` (`success` / `error` status in `raw_event`) |
| graph paused by `interrupt()` | `RUN_FINISHED` with an interrupt outcome; the answer arrives as `resume` |
| invocation ends / raises | `RUN_FINISHED` / `RUN_ERROR` |

Models that do not stream still work: the finished message is used to fill in text and tool calls. The dev pane
(`d` or `/dev`) shows both sides: lines starting with `langchain` are the LangChain events, the JSON lines are the
AG-UI events.

**Multi-turn.** Memory is the graph's checkpointer, keyed by Gentui's thread id. If the graph has none, Gentui gives it
an in-memory one. `/new` starts a fresh thread.

## In the browser

`gentui --serve` serves the same UI in a web page (`pip install 'gentui[web]'`). For a native agent, serve your script
with textual-serve: `Server("python my_agent.py").serve()`. See the [command-line reference](cli.md#in-the-browser).

## Limitations

- No reasoning is shown unless the model returns it (see [Showing the model's thinking](#showing-the-models-thinking)).
- Interrupts are answered as yes / no; free-form input is not supported yet.
- A tool's result is shown as text; images and files appear as `[image]` / `[file]`.
- Shared state (`STATE_SNAPSHOT`, the plan widget) is not produced.
- Text from sub-agents run inside tools is shown as part of the chat.

## Examples

[`examples/langchain_native/`](https://github.com/rahrajlat/Gentui/tree/main/examples/langchain_native) has
`tool_call.py`, `tool_call_approval.py` and `chart.py`. They need `pip install 'gentui[langchain,langchain-ollama]'` and
a running, signed-in Ollama for their model. The tests need none of that: they drive a real LangChain agent with a
scripted model.
