# Extending Gentui

Everything is a plugin: drop in a file, add one decorator, restart the backend. Nothing else
in the codebase changes. Working examples ship with the repo:
[`system_info.py`](../src/gentui/backend/tools/system_info.py),
[`explainer_agent.py`](../src/gentui/backend/agents/explainer_agent.py),
[`table.py`](../src/gentui/tui/widgets/table.py).

## 1. Add a tool

Create `src/gentui/backend/tools/my_tool.py`:

```python
from strands import tool
from gentui.backend.registry import register_tool

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

Create `src/gentui/backend/agents/my_agent.py`:

```python
from strands import Agent
from strands_harness import create_harness
from gentui.backend.config import get_settings
from gentui.backend.models import make_model
from gentui.backend.registry import register_agent

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

## 3. Add a widget ("the tool call IS the UI")

Create `src/gentui/tui/widgets/my_widget.py` and import it in `widgets/__init__.py`:

```python
from rich.text import Text
from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

@register_widget("word_count")          # tool name -> widget
class WordCountWidget(ToolWidget):
    def on_start(self):                 # TOOL_CALL_START: show a skeleton right away
        self.show(Text("counting…", style="dim italic"))

    def on_end(self, args):             # TOOL_CALL_END: final arguments are in
        self.show(Text(f"{len(args['text'].split())} words"))

    def on_result(self, text):          # TOOL_CALL_RESULT: what the tool returned
        ...
```

Lifecycle: `on_start` → `on_args` (repeatedly, as the JSON arrives) → `on_end` → `on_result`.
Ollama usually sends the args in one piece, so the skeleton in `on_start` is what makes it feel live.

Unknown tools fall back to `GenericToolWidget`, so a widget is always optional.

### Talking back to the agent (buttons, forms)

Call `self.submit("text for the agent", {"some": "props"})`. The app sends it as the **next
user message**; `props` travel out-of-band in AG-UI `forwardedProps` (the model never sees them).
The `CommandWidget` uses exactly this for Approve / Edit / Reject.

*Trade-off:* true AG-UI "frontend tools" would let the agent *wait* for the click inside a
single run. Sending a new user message is simpler (no pause/resume, no interrupt plumbing),
at the cost of the run ending at each decision point.

## 4. Shared state

Backend state that the UI should mirror lives in `agent.state`. `app._shared_state()` projects it
(today: the harness `todo_write` plan) and the adapter emits `STATE_SNAPSHOT` once per run and
`STATE_DELTA` (JSON Patch) after each tool result. In the TUI, `GentuiApp._on_state_changed` is
where state becomes widgets (the `PlanWidget` is updated in place).

## 5. Swap the model

One line in `.env`: `GENTUI_MODEL=<provider>/<model>` (ollama, openai, anthropic, google,
bedrock, bedrock-mantle, litellm). For anything custom, return a Strands `Model` instance from
`backend/models.py:make_model`.
