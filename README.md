# Gentui

**Generative UI for your terminal.** Ask for a shell task in plain English; an agent proposes a
command, the TUI renders it as an interactive widget, and **nothing runs until you approve it**.

Built with the [Strands Agents harness](https://strandsagents.com/docs/user-guide/harness/),
the [AG-UI protocol](https://docs.ag-ui.com), FastAPI and [Textual](https://textual.textualize.io).

```
 tui (Textual) ── POST /agent (RunAgentInput) ──▶ any AG-UI backend
      ▲                                                  │
      │◀──────────── SSE: AG-UI events ─────────────────┘

 Approve ▸ forwardedProps.approval ──▶ backend (your own) ──▶ runs the approved command
```

This repo contains **only the terminal client**. It speaks the open AG-UI protocol, so it works with
any backend that serves an AG-UI endpoint (default `http://localhost:8000/agent`). The reference
backend (Strands harness + FastAPI) is kept out of version control.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12).

```bash
uv sync
uv run gentui http://localhost:8000/agent                  # point at any AG-UI backend
uv run gentui https://my.host/agent --token sk-...         # with auth (Bearer)
uv run gentui URL -H "X-Org: acme" --theme nord --dev      # headers, theme, event inspector
```

Streaming text, the model's chain of thought, tool calls (as widgets or a JSON card), shared
state and errors work with **any** AG-UI backend, with no setup. Keys: `Enter` send ·
`d` / `Ctrl+D` event inspector · `Ctrl+Q` quit. Type `/help` for slash commands
(`/theme`, `/clear`, `/reasoning`, `/dev`, `/quit`).

## Configure

Put options in `./gentui.toml` or `~/.config/gentui/config.toml`; flags and `GENTUI_URL` /
`GENTUI_TOKEN` override them. Every option is documented in
[`gentui.example.toml`](gentui.example.toml): backend URL, token and headers, props sent with every
run, title, welcome text, prompt placeholder, theme, reasoning on/off, plugins, widget mapping.

## Customise the UI

- **Theme:** `theme = "nord"` or `/theme <name>`.
- **Your own styling:** `css = "my.tcss"` loads a [Textual CSS](https://textual.textualize.io/guide/CSS/)
  file on top of the defaults and **hot-reloads while the app runs**. Useful selectors: `.user`,
  `.assistant`, `.thinking`, `.error`, `ToolWidget`, `#chat`, `#prompt`.
- **Your own widget for a backend tool:** subclass `ToolWidget` (it is called with the tool's
  streamed arguments and result), then map it without any plugin file:

  ```toml
  [widgets]
  show_map = "my_widgets:MapWidget"
  ```

## Add features (plugins)

A plugin is a plain Python file. Drop it in `./gentui_plugins/`, `~/.config/gentui/plugins/`, list it
in `plugins = [...]` / `--plugin`, or ship it as a pip package using the `gentui.plugins` entry point.

```python
from gentui.plugins import on_event, register_command
from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

@register_widget("weather")                  # render tool calls named "weather"
class Weather(ToolWidget):
    def on_end(self, args): self.show(f"☀ {args['city']}")

@register_command("ping", "say pong")        # adds /ping
def ping(app, args): app.notify("pong")

@on_event("TOOL_CALL_RESULT")                # hook any AG-UI event
async def audit(app, event): ...

def setup(app): ...                          # optional, runs once the app is mounted
```

Plugins can mount any Textual widget into the conversation with `await app.mount_chat(widget)`.
A broken plugin is reported in a toast; it never stops the app.

## Built-in widgets (the tool contract)

A backend gets these widgets by naming its tools like this; anything else shows a JSON card (or your
`default_widget`).

| Tool name | Arguments / result | Renders |
|---|---|---|
| `propose_command` | `{command, explanation, risk: safe\|caution\|danger}` | command card with Approve / Edit / Reject (the click is sent back as the next message, with `forwardedProps.approval`) |
| `run_command` | result JSON `{command, exit_code, timed_out, truncated, output}` | output card |
| `show_table` | `{title, columns, rows}` | table |
| `show_chart` | `{type: line\|bar\|scatter\|histogram, title, x, series: [{name, values}], x_label, y_label, bins}` | terminal chart (plotext) |
| `search_memory` | `{query}` | quiet "🧠 recalled …" line |
| `todo_write` + state `plan` | state `{"plan": [{content, status}]}` | live checklist |

## How it works

| Piece | File |
|---|---|
| SSE client (RunAgentInput in, typed events out) | [`tui/agui_client.py`](src/gentui/tui/agui_client.py) |
| TUI: event → widget dispatch | [`tui/app.py`](src/gentui/tui/app.py) |
| Widgets + tool-name registry | [`tui/widgets/`](src/gentui/tui/widgets) |

AG-UI events used: `RUN_STARTED/FINISHED/ERROR`, `TEXT_MESSAGE_START/CONTENT/END`,
`REASONING_*` (chain of thought, shown as a collapsible "Thought" block),
`TOOL_CALL_START/ARGS/END/RESULT`, `STATE_SNAPSHOT`, `STATE_DELTA`.

### Design notes

- *Generative UI = the tool call is the UI.* The widget spec is the tool's arguments; the TUI renders
  from `TOOL_CALL_*` events and shows a skeleton on `TOOL_CALL_START`.
- *Clicks go back as the next user message* (plus out-of-band `forwardedProps`), the simplest option.
- Widgets are chosen by tool name (`tui/widgets/registry.py`); unknown tools fall back to a generic JSON card.

## Develop

```bash
uv run pytest -q     # headless TUI tests (no LLM or backend needed)
```
gentui http://localhost:8000/agent  