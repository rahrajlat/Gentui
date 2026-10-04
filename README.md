<div align="center">

<img src="docs/assets/hero.gif" alt="Gentui: generative UI for your terminal" width="640">

**A terminal client for [AG-UI](https://docs.ag-ui.com) agent backends.**<br>
Streaming chat, the model's chain of thought, tables, charts and human approval,<br>
drawn as live widgets in your terminal.

[![CI](https://img.shields.io/github/actions/workflow/status/rahrajlat/Gentui/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/rahrajlat/Gentui/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Textual](https://img.shields.io/badge/built%20with-Textual-4FD6C8?style=flat-square)](https://textual.textualize.io)
[![AG-UI](https://img.shields.io/badge/protocol-AG--UI-A78BFA?style=flat-square)](https://docs.ag-ui.com)
[![Tested with Strands Agents](https://img.shields.io/badge/tested%20with-Strands%20Agents%20(AWS)-FF9900?style=flat-square)](https://strandsagents.com)
[![uv](https://img.shields.io/badge/packaged%20with-uv-DE5FE9?style=flat-square)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/license-MIT-7BD88F?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-F2C46D?style=flat-square)](#status)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-7BD88F?style=flat-square)](#contributing)
[![Stars](https://img.shields.io/github/stars/rahrajlat/Gentui?style=flat-square&color=4FD6C8)](https://github.com/rahrajlat/Gentui/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/rahrajlat/Gentui?style=flat-square&color=A78BFA)](https://github.com/rahrajlat/Gentui/commits/main)

</div>

---

## Why Gentui?

While developing agents locally, we end up spending our time on the frontend: a Streamlit or Chainlit
app, or a React project, just to talk to the agent. Each one is a separate frontend to build and keep
running.

Gentui removes that step. Install it, point it at your agent's AG-UI endpoint, and you get a chat, the
model's **chain of thought**, **human-in-the-loop (HITL)** and **approval** flows out of the box, with no
frontend code to write.

Point Gentui at any backend that speaks AG-UI and you get a polished terminal interface with no
frontend code to write. When the agent calls a tool, the **tool call becomes the UI**: a command to
approve, a table, a chart, a live plan. Nothing risky runs until you click **Approve**.

**Tested with the [Strands Agents](https://strandsagents.com) framework (AWS's open-source agent SDK) over
AG-UI**: both on a custom backend (the [example backend](examples/strands-backend)) and on the official
[`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter.

<div align="center">
<img src="docs/assets/demo.gif" alt="Gentui demo: ask, review the proposed command, approve, see the output, chart it" width="860">
</div>

## Features

- **Works with any AG-UI backend.** Streaming text, tool calls and shared state work out of the box;
  unknown tools show as a readable card, never an error.
- **Chain of thought, visible.** Reasoning streams into a collapsible "Thought for 3s" block.
- **Human-in-the-loop approval** built on AG-UI **interrupts**: the run ends waiting, your click
  `resume`s it. The model can't approve its own commands.
- **Generative widgets from tool calls:** command card, command output, tables, terminal charts
  (line, bar, scatter, histogram), live plan checklist.
- **Developer-friendly:** an event inspector (`d`) showing the raw SSE payloads exactly as sent, `/theme`,
  `/clear`, `/reasoning`, and a clear [backend contract](docs/tool-contract.md).
- **Yours to customise:** TOML config, hot-reloaded CSS, your own themes, and Python plugins that add
  widgets, slash commands and event hooks.
- **Backend-agnostic by design.** The client has no framework code; a complete example backend lives in
  [`examples/strands-backend`](examples/strands-backend).

## The sample agent: natural language → shell

The demo above is the bundled example backend, a **natural-language-to-shell agent** built on Strands
Agents. You describe a task in plain English, it proposes a single shell command, and **nothing runs
until you approve it**.

1. **Ask:** "what are the 5 largest files here?"
2. **Review:** a shell sub-agent writes one command for your shell (bash, or PowerShell on Windows)
   with a one-line explanation and a risk level: `safe`, `caution` or `dangerous`.
3. **Decide:** **Approve**, **Edit** the command first, or **Reject**. Your decision is sent back as an
   AG-UI `resume`; the model can't approve for itself or change the command.
4. **Run:** only the approved command executes, with a timeout, an output cap and a fixed working
   directory. A denylist (recursive delete of root or home, disk formatting, shutdown, fork bombs,
   interactive programs) is checked at proposal, at approval and again right before running. It is a
   safety net, not a sandbox.

The same agent can also show results as a **table** or **chart**, lay out multi-step work as a live
**plan**, explain what a command does (an explainer sub-agent), and keep **long-term memory** between
conversations. It's a worked example of the [backend contract](docs/tool-contract.md): copy it, or add your
own tools with [this guide](examples/strands-backend/docs/add_a_tool.md).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
git clone https://github.com/rahrajlat/Gentui.git && cd Gentui
uv sync
uv run gentui http://localhost:8000/agent        # your AG-UI endpoint
```

No backend yet? Run the [sample natural-language-to-shell agent](#the-sample-agent-natural-language--shell)
(Strands Agents + FastAPI) in another terminal. It uses a local
[Ollama](https://ollama.com) by default; see its [README](examples/strands-backend/README.md) for other providers:

```bash
cd examples/strands-backend
uv sync && cp .env.example .env
uv run server                                     # http://localhost:8000/agent
```

```bash
uv run gentui https://my.host/agent --token sk-...        # bearer auth
uv run gentui URL -H "X-Org: acme" --theme nord --dev     # extra header, theme, event inspector
```

| Key / command | Does |
|---|---|
| `Enter` | send |
| `d` or `Ctrl+D` | toggle the event inspector |
| `Ctrl+Q` | quit |
| `/help` `/theme <name>` `/clear` `/reasoning` `/dev` `/quit` | slash commands |

## Configure

Put options in `./gentui.toml` or `~/.config/gentui/config.toml`. Flags, `GENTUI_URL` and
`GENTUI_TOKEN` override the file. Every option is documented in
[`gentui.example.toml`](gentui.example.toml): backend URL, token and headers, props sent with every run,
title, welcome text, theme, splash and logo, reasoning on/off, timestamps, plugins and widget mapping.

> **Stateless backends** (ones that rebuild context from the message list, like the official
> `ag-ui-strands` adapter) need `send_history = true`. By default only the newest message is sent and
> the backend is expected to keep history per `threadId`.

## Customise

- **Theme:** `theme = "nord"` or `/theme <name>`. The default is `gentui` (teal and violet); `claude`
  (coral) is also built in.
- **Your own styling:** `css = "my.tcss"` loads a [Textual CSS](https://textual.textualize.io/guide/CSS/)
  file on top of the defaults and **hot-reloads while the app runs**. Useful selectors: `.user`,
  `.assistant`, `.thinking`, `.error`, `ToolWidget`, `#chat`, `#prompt`.
- **Your own widget for a backend tool:** subclass `ToolWidget`, then map it without any plugin file:

  ```toml
  [widgets]
  show_map = "my_widgets:MapWidget"
  ```

## Plugins

A plugin is a plain Python file. Drop it in `./gentui_plugins/` or `~/.config/gentui/plugins/`, list it in
`plugins = [...]` or `--plugin`, or ship it as a pip package using the `gentui.plugins` entry point.

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

Plugins can mount any Textual widget into the conversation with `await app.mount_chat(widget)`. A
broken plugin is reported in a toast and never stops the app.

## Build a backend for it

Any language works: serve a `POST` endpoint that streams AG-UI events. To get the rich widgets, name
your tools like this (anything else shows a JSON card). The full contract, including the approval
flow and a checklist, is in **[docs/tool-contract.md](docs/tool-contract.md)**.

| Tool name | Arguments / result | Renders |
|---|---|---|
| `propose_command` | `{command, explanation, risk: safe\|caution\|dangerous}` | command card with Approve / Edit / Reject; the decision goes back as an AG-UI `resume` of the run's interrupt |
| `run_command` | result JSON `{command, exit_code, timed_out, truncated, output}` | output card |
| `show_table` | `{title, columns, rows}` | table |
| `show_chart` | `{type: line\|bar\|scatter\|histogram, title, x, series: [{name, values}], x_label, y_label, bins}` | terminal chart (plotext) |
| `search_memory` | `{query}` | quiet "◌ recalled …" line |
| `todo_write` + state `plan` | state `{"plan": [{content, status}]}` | live checklist |

## How it works

```
 gentui (Textual) ── POST /agent (RunAgentInput) ──▶ any AG-UI backend
      ▲                                                    │
      │◀────────────── SSE: AG-UI events ─────────────────┘

 Approve ▸ `resume` of the run's interrupt ──▶ backend runs the approved command
```

| Piece | File |
|---|---|
| SSE client (RunAgentInput in, typed events out) | [`tui/agui_client.py`](src/gentui/tui/agui_client.py) |
| Event → widget dispatch, interrupts, chat | [`tui/app.py`](src/gentui/tui/app.py) |
| Widgets and the tool-name registry | [`tui/widgets/`](src/gentui/tui/widgets) |
| Logo, splash and animation | [`tui/branding.py`](src/gentui/tui/branding.py), [`tui/splash.py`](src/gentui/tui/splash.py) |
| Plugin API and config | [`plugins.py`](src/gentui/plugins.py), [`config.py`](src/gentui/config.py) |

AG-UI events used: `RUN_STARTED/FINISHED/ERROR` (with `outcome: interrupt`), `TEXT_MESSAGE_*`,
`REASONING_*`, `TOOL_CALL_START/ARGS/END/RESULT`, `STATE_SNAPSHOT`, `STATE_DELTA`. The request side
uses `messages`, `forwardedProps` and `resume`.

## Status

Gentui is **alpha**. What has been verified, and what has not:

- Built and tested against the **Strands Agents** framework (AWS) over AG-UI: the
  [example backend](examples/strands-backend) and the official
  [`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter (with `send_history = true`).
- Backends on other frameworks, the interrupt flow against a backend other than the example, other model
  providers than Ollama, and native Windows are **untested**.
- The look relies on Unicode box-drawing and block characters. If glyphs are missing, try a terminal
  font such as DejaVu Sans Mono, Cascadia or JetBrains Mono.

**Ideas, not built yet:** `show_form` / `ask_approval` tools, a composable JSON-tree UI tool, persistent
threads, a `--demo` mode and record/replay of runs.

## Development

```bash
uv run pytest -q                                   # TUI tests: headless, no LLM or backend needed
cd examples/strands-backend && uv run pytest -q    # the example backend's own tests
```

The images above are generated from the app's own code:
`uv run --with pillow python docs/assets/build_assets.py`.

## Contributing

Issues and pull requests are welcome. Please run both test suites before opening a PR, and add a test
with any behaviour change. Because Gentui is a client for an open protocol, changes that keep it
backend-agnostic are the easiest to accept.

## License

[MIT](LICENSE). Free to use, modify and distribute, including the [example backend](examples/strands-backend).
