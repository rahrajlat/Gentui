# Gentui: session notes (resume here)

Saved 2026-10-04. This is a summary of the build session, not a verbatim transcript.

## Goal
Terminal "generative UI" agent: a Strands **harness** orchestrator (any model) behind a FastAPI
**AG-UI** SSE endpoint, with a **Textual** TUI that renders chat plus tool-call widgets.
First capability: natural language → shell command, with human approval before anything runs.
It's a learning project and a LinkedIn screen-recording demo.

## Decisions made (and why)
- **Strands harness, not plain Agent.** `create_harness()` returns a plain `strands.Agent`.
  We switch off most built-ins (`builtin_tools=[]`, no memory/session/skills) and keep only
  `builtin_plugins=["todos"]` (its `todo_write` drives the plan widget).
- **Model = one config string**, `GENTUI_MODEL=<provider>/<model>`. Providers: ollama, openai,
  anthropic, google, bedrock, bedrock-mantle, litellm. Default `ollama/gpt-oss:120b-cloud` via the
  local Ollama (signed in, no API key). Custom model: return a `Model` instance from `backend/models.py`.
- **Own AG-UI adapter**, not the official `ag-ui-strands` (~12k lines; covers interrupts, frontend
  tools, A2UI). Ours is ~150 lines in `backend/agui_adapter.py`.
- **Layout:** `src/gentui/backend/` and `src/gentui/tui/` (not top-level folders).
- **Approvals are out-of-band.** The TUI sends `forwardedProps.approval`; the backend stores
  `{approval_id: command}` in `agent.state`; the model only passes the id to `run_command`.
  Reason: the model mangled `\n` when retyping a command.
- **`propose_command` is private to the shell sub-agent** (not registered on the orchestrator), and
  `shell_agent` uses `delegate=True` so the turn ends after a proposal.
- **Button clicks go back as the next user message** (simplest; trade-off documented in
  `examples/add_a_tool.md`).
- **VS Code tasks:** only `Backend` and `Frontend`. No per-milestone scripts.

## Current state: everything below is implemented
- Backend: `app.py` (POST /agent, GET /health), `agui_adapter.py` (text, tool calls, results, nested
  sub-agent tool calls, STATE_SNAPSHOT/DELTA via jsonpatch), `registry.py`, `orchestrator.py`,
  `tools/shell.py` + `shell_safety.py`, `tools/ui.py` (`show_table`), `tools/system_info.py` (sample),
  `agents/shell_agent.py`, `agents/explainer_agent.py` (sample).
- TUI: `app.py`, `agui_client.py`, widgets: command (Approve/Edit/Reject), output, plan, table,
  generic fallback, plus a registry. Dev pane on `d` / `Ctrl+D`.
- Docs: `README.md` (diagram, setup, demo script), `examples/add_a_tool.md`.
- Tests: 50 pass (`uv run pytest -q`), no LLM needed.
- Verified live against `gpt-oss:120b-cloud`: propose → approve → run → output; plan widget;
  `show_table`; explainer sub-agent. Nothing is committed yet.

## Run
```bash
uv sync
uv run server                                  # backend :8000
uv run tui --url http://localhost:8000/agent   # TUI
```
VS Code: Run Task → Backend, then Frontend. Command log: `.agent/commands.log`.

## Gotchas learned
- Don't name attributes or methods on Textual `App` / `Widget` subclasses `_running`, `_render`,
  `_queue`, etc. They shadow Textual internals and break it silently.
- `ev.delta` on `STATE_DELTA` holds pydantic objects. Convert with `model_dump(by_alias=True,
  exclude_none=True)` before `jsonpatch`.
- Harness `background_tasks` injects a `_background_execution` tool arg. Keep `background_tasks=False`.
- Agents print to stdout unless `callback_handler=None`.
- `pkill -f` can kill your own shell. Stop the server by its listening PID.

## Not verified / known limits
- Windows (PowerShell path) untested; developed on WSL.
- Providers other than Ollama untested.
- The TUI's look hasn't been reviewed by eye; check before recording.
- The denylist was only unit-tested. The live model refused `rm -rf ~` on its own.
- `d` doesn't toggle the dev pane while the prompt is focused (`Ctrl+D` always works).
- The plan widget stays where it was first created and can scroll out of view.
- History is in memory per `thread_id` and is lost on restart.

## Ideas for next steps
- Commit the work (nothing is committed yet).
- Review the TUI visually and polish the theme for the recording.
- `show_form` and `ask_approval` UI tools (in the original spec, not built yet).
- Quiet `ActivityWidget` for `explainer_agent`; today it falls back to a JSON card.
- Persist threads and sessions (the harness `session=` option).
- Native Windows run-through, then try another provider via `GENTUI_MODEL`.
- Compare with `ag-ui-strands` on interrupt-based approval (true frontend tools).
