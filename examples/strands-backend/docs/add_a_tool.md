# Extending the Strands example backend

Everything is a plugin: drop in a file, add one decorator, restart the backend. Nothing else
in the codebase changes. Working examples ship with this backend:
[`system_info.py`](../src/strands_backend/tools/system_info.py),
[`explainer_agent.py`](../src/strands_backend/agents/explainer_agent.py),
[`ui.py`](../src/strands_backend/tools/ui.py) (`show_table`, `show_chart`).

## 1. Add a tool

Create `src/strands_backend/tools/my_tool.py`:

```python
from strands import tool
from strands_backend.registry import register_tool

@register_tool          # <- collects it for the orchestrator
@tool                   # <- Strands: the docstring + type hints become the tool schema
def word_count(text: str) -> int:
    """Count the words in a piece of text.

    Args:
        text: The text to count.
    """
    return len(text.split())
```

That's it. `registry.discover()` imports every module in `tools/`, so the orchestrator
picks it up automatically. In the TUI it appears as a generic JSON card (see step 3 to
give it a real widget).

## 2. Add a sub-agent ("agent as tool")

Create `src/strands_backend/agents/my_agent.py`:

```python
from strands import Agent
from strands_harness import create_harness
from strands_backend.config import get_settings
from strands_backend.models import make_model
from strands_backend.registry import register_agent

@register_agent()                      # or register_agent(delegate=True), see below
def my_agent() -> Agent:
    return create_harness(
        model=make_model(),
        effort=get_settings().effort,
        name="my_agent",               # becomes the tool name
        description="One sentence the orchestrator reads to decide when to call you.",
        instructions="The sub-agent's own system prompt.",
        callback_handler=None,         # keep stdout clean; events are streamed instead
        tools=[],                      # give it its own tools here
        builtin_tools=[], builtin_plugins=[], background_tasks=False, memory=False,
        session=False, skills=False, context_manager=False, caching=False,
    )
```

- Each sub-agent has its **own prompt and tools**; the orchestrator only sees it as one tool.
- `delegate=True` ends the turn with the sub-agent's reply (no further orchestrator model call).
  The shell agent uses this so that once a command is proposed, the *user* decides next.
- A tool that should be **private to a sub-agent** (like `propose_command`) is *not*
  decorated with `@register_tool`; pass it in that sub-agent's `tools=[...]` only.
- Tool calls a sub-agent makes are forwarded to the TUI too, so they can have widgets.

## 3. Give the tool a widget (in the Gentui TUI)

A tool you add shows up in the TUI as a generic JSON card. To draw it properly, write a TUI
widget: either a plugin file or a `[widgets]` entry in `gentui.toml`, with no change to the TUI
itself. See "Customise the UI" and "Add features (plugins)" in the
[main README](../../../README.md), and the argument shapes of the built-in widgets in the
[backend contract](../../../docs/tool-contract.md).

The tool call is the UI: the widget is drawn from the tool's **arguments** as they stream in
(`on_start`, `on_args`, `on_end`) and from its **result** (`on_result`).

### Waiting for the user (approval)

Approval uses AG-UI interrupts, implemented in
[`approvals.py`](../src/strands_backend/approvals.py): when the model proposes a command, the run
ends with `RUN_FINISHED` carrying an `interrupt` outcome, and the TUI continues it with a `resume`.
To make another tool wait for a decision the same way, follow that module and section 4 of the
[backend contract](../../../docs/tool-contract.md).

## 4. Shared state

Backend state that the UI should mirror lives in `agent.state`. `app._shared_state()` projects it
(today: the harness `todo_write` plan) and the adapter emits `STATE_SNAPSHOT` once per run and
`STATE_DELTA` (JSON Patch) after each tool result. In the TUI, the `plan` key of that state drives the plan checklist (see the backend contract).

## 5. Swap the model

One line in `.env`: `GENTUI_MODEL=<provider>/<model>` (ollama, openai, anthropic, google,
bedrock, bedrock-mantle, litellm). For anything custom, return a Strands `Model` instance from
`src/strands_backend/models.py:make_model` (it already returns an Ollama model that streams the model's
reasoning, so the TUI can show its chain of thought).
