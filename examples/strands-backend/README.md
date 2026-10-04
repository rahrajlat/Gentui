# Strands example backend

An example **AG-UI backend** for the [Gentui](../../README.md) terminal client, built on the
[Strands Agents harness](https://strandsagents.com/docs/user-guide/harness/) with FastAPI. It is a
separate project with its own dependencies: Gentui itself needs none of them.

It turns plain English into a shell command, shows it for approval, and only then runs it. It also
has a table tool, a chart tool, a plan (`todo_write`), long-term memory and an explainer sub-agent.
Approval uses AG-UI **interrupts**: see [approvals.py](src/strands_backend/approvals.py) and the
[backend contract](../../docs/tool-contract.md).

## Run

```bash
cd examples/strands-backend
uv sync
cp .env.example .env          # defaults work if Ollama is installed and signed in (`ollama signin`)
uv run server                 # http://localhost:8000/agent
```

Then, from the repository root, in another terminal:

```bash
uv run gentui http://localhost:8000/agent
```

(VS Code: **Terminal ▸ Run Task…** → `Backend`, then `Frontend`.)

Stop the server with **Ctrl+C**: that is when pending long-term memory is written to disk.

## Configure (`.env`)

| Variable | Meaning |
|---|---|
| `GENTUI_MODEL` | `<provider>/<model>`: `ollama`, `openai`, `anthropic`, `google`, `bedrock`, `bedrock-mantle`, `litellm` |
| `GENTUI_EFFORT` | reasoning effort: `auto`, `off`, `minimal` … `max` |
| `GENTUI_MEMORY`, `GENTUI_MEMORY_DIR` | long-term memory on/off (default on) and its folder (`./.agent/memory`) |
| `GENTUI_SHELL_CWD`, `GENTUI_SHELL_TIMEOUT`, `GENTUI_SHELL_MAX_OUTPUT` | where approved commands run, their timeout (30 s) and output cap (8000 chars) |
| provider credentials | `OLLAMA_HOST`, `OLLAMA_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, AWS variables |

The `GENTUI_` prefix is kept so existing `.env` files keep working. Run the server from this folder
so `.env` and `.agent/` (command log, memory) are found here.

## Layout

| File | Role |
|---|---|
| [`app.py`](src/strands_backend/app.py) | `POST /agent` (SSE), per-thread agents, resume handling, shutdown flush |
| [`agui_adapter.py`](src/strands_backend/agui_adapter.py) | Strands stream events → AG-UI events (text, reasoning, tool calls, state) |
| [`approvals.py`](src/strands_backend/approvals.py) | propose → interrupt → resume → run |
| [`orchestrator.py`](src/strands_backend/orchestrator.py) | the main agent, built from the registry |
| [`registry.py`](src/strands_backend/registry.py) | `@register_tool` / `@register_agent` plugin discovery |
| [`models.py`](src/strands_backend/models.py) | which LLM backs the agents (Ollama streams its reasoning) |
| `tools/`, `agents/` | shell, table, chart, system info; the shell and explainer sub-agents |

Add your own tool or sub-agent: [docs/add_a_tool.md](docs/add_a_tool.md).

## Safety model

- **No execution without approval.** The harness's built-in `shell` tool is disabled. The only path
  is `shell_agent` → `propose_command` (records only) → *you click Approve* → `run_command`.
- **The model can't approve itself or alter a command.** The backend remembers the proposed command
  against the interrupt id; the client only says yes or no (or sends an edit, which is re-checked).
  One approval means one run.
- **Denylist** (recursive delete of root/home/drives, disk formatting, shutdown/reboot, registry edits,
  fork bombs, interactive programs) is enforced at proposal, at approval and right before execution.
  It is a safety net, not a sandbox.
- 30 s timeout, output cap, configurable working directory, stdin closed. Every proposed, approved
  and executed command is logged to the console and `.agent/commands.log`.

## Develop

```bash
uv run pytest -q              # adapter, registry, safety rules, interrupts (no LLM needed)
```
