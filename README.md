# Gentui

**Generative UI for your terminal.** Ask for a shell task in plain English; an agent proposes a
command, the TUI renders it as an interactive widget, and **nothing runs until you approve it**.

Built with the [Strands Agents harness](https://strandsagents.com/docs/user-guide/harness/),
the [AG-UI protocol](https://docs.ag-ui.com), FastAPI and [Textual](https://textual.textualize.io).

```
 tui (Textual) ── POST /agent (RunAgentInput) ──▶ FastAPI ──▶ Orchestrator (Strands harness)
      ▲                                                          ├─ tools        (registry)
      │◀──────────── SSE: AG-UI events ─────────────────────────┤─ sub-agents   (agents as tools)
                                                                 └─ any model    (GENTUI_MODEL)

 Approve ▸ forwardedProps.approval ──▶ backend records {approval_id: command} ──▶ run_command(approval_id)
```

## Setup

Requires [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned in `.python-version`).

```bash
uv sync
cp .env.example .env     # defaults work if Ollama is installed and signed in (`ollama signin`)
```

`.env` — the model is a single `<provider>/<model>` string; the harness reads provider
credentials from the environment:

| Provider | Example |
|---|---|
| Ollama (local host proxying cloud models) | `GENTUI_MODEL=ollama/gpt-oss:120b-cloud` |
| Ollama Cloud direct | `OLLAMA_HOST=https://ollama.com`, `OLLAMA_API_KEY=...` |
| OpenAI / Anthropic / Google / Bedrock | `GENTUI_MODEL=openai/<model>` + the provider's usual API key env var |

Shell limits: `GENTUI_SHELL_CWD` (default `.`), `GENTUI_SHELL_TIMEOUT` (30 s), `GENTUI_SHELL_MAX_OUTPUT` (8000 chars).

## Run

VS Code: **Terminal ▸ Run Task…** → `Backend`, then `Frontend`. Or in two terminals:

```bash
uv run server                                    # backend on http://localhost:8000
uv run tui --url http://localhost:8000/agent     # TUI
```

Keys: `Enter` send · `d` / `Ctrl+D` toggle the dev pane (raw AG-UI events + shared state) · `Ctrl+Q` quit.

## How it works

| Piece | File |
|---|---|
| Strands event → AG-UI event translation (the core idea) | [`agui_adapter.py`](src/gentui/backend/agui_adapter.py) |
| SSE endpoint, per-thread agents, approval hook | [`app.py`](src/gentui/backend/app.py) |
| Plugin registry (`@register_tool`, `@register_agent`) | [`registry.py`](src/gentui/backend/registry.py) |
| Orchestrator (harness) built from the registry | [`orchestrator.py`](src/gentui/backend/orchestrator.py) |
| Shell flow: propose → approve → run, with safety denylist | [`tools/shell.py`](src/gentui/backend/tools/shell.py), [`tools/shell_safety.py`](src/gentui/backend/tools/shell_safety.py) |
| TUI: event → widget dispatch | [`tui/app.py`](src/gentui/tui/app.py) |
| Widgets + tool-name registry | [`tui/widgets/`](src/gentui/tui/widgets) |

AG-UI events used: `RUN_STARTED/FINISHED/ERROR`, `TEXT_MESSAGE_START/CONTENT/END`,
`TOOL_CALL_START/ARGS/END/RESULT`, `STATE_SNAPSHOT`, `STATE_DELTA`.

### Safety model

- **No execution without approval.** The harness's built-in `shell` tool is disabled. The only
  path is `shell_agent` → `propose_command` (records only) → *you click Approve* → `run_command`.
- **The model can't approve itself or alter a command.** Approvals travel out-of-band
  (`forwardedProps`), are stored server-side as `{approval_id: command}`, and the model only
  passes the id. One approval = one run.
- **Denylist** (recursive delete of root/home/drives, disk formatting, shutdown/reboot, registry
  edits, fork bombs, interactive programs) is enforced at proposal, at approval *and* right before
  execution — approval cannot override it. It's a safety net, not a sandbox.
- 30 s timeout, output cap, configurable working directory, stdin closed.
- Every proposed / approved / executed command is logged to the console and `.agent/commands.log`.

### Design notes

- *Generative UI = the tool call is the UI.* The widget spec is the tool's arguments; the TUI renders
  from `TOOL_CALL_*` events and shows a skeleton on `TOOL_CALL_START`.
- *Own adapter vs `ag-ui-strands`.* The official package (~12k lines) also covers interrupts, frontend
  tools, citations and A2UI. Ours is ~150 readable lines focused on this project's flow.
- *Clicks go back as the next user message* — simplest option; see
  [`examples/add_a_tool.md`](examples/add_a_tool.md) for the trade-off vs AG-UI frontend tools.
- Conversation history lives in the backend per `thread_id` (in memory; lost on restart).

## Extend it

Add a tool, sub-agent or widget with one file and one decorator: **[examples/add_a_tool.md](examples/add_a_tool.md)**.

## Develop

```bash
uv run pytest -q     # adapter, safety rules, headless TUI tests (no LLM needed)
```

## Demo script (screen recording, ~90 s)

Start both tasks; press `d` once to show the dev pane, then:

1. **Ask:** `what are the 5 largest files in this folder?`
   → skeleton appears, then the command card with a green **SAFE** badge. Point at the dev pane
   streaming `TOOL_CALL_START → ARGS → END`.
2. Click **Edit**, change `head -n 5` to `head -n 3`, click **Approve edit**
   → output card with exit code; the log line in `.agent/commands.log`.
3. **Ask a multi-step task:** `plan how to check the python version and disk usage, then do the first step`
   → the **Plan** checklist appears and ticks in place (dev pane: `STATE_DELTA`).
4. **Show the table widget:** `get the system info and show it as a table`.
5. **Show safety:** `delete everything in my home folder with rm -rf ~`
   → refused (by the model, or blocked by the policy even if it were proposed).
6. **Show extensibility:** open `examples/add_a_tool.md`; `system_info.py` is the whole tool.
