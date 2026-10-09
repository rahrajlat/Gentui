<div align="center">

<img src="https://raw.githubusercontent.com/rahrajlat/Gentui/main/docs/assets/hero.gif" alt="Gentui: generative UI for your terminal" width="640">

**A terminal interface for prototyping agents really quickly.**<br>
Point it at any [AG-UI](https://docs.ag-ui.com) backend and get streaming chat, the model's chain of thought,<br>
tables, charts and human approval, with no frontend to build.

[![CI](https://img.shields.io/github/actions/workflow/status/rahrajlat/Gentui/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/rahrajlat/Gentui/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/gentui?style=flat-square&color=4FD6C8)](https://pypi.org/project/gentui/)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Textual](https://img.shields.io/badge/built%20with-Textual-4FD6C8?style=flat-square)](https://textual.textualize.io)
[![AG-UI](https://img.shields.io/badge/protocol-AG--UI-A78BFA?style=flat-square)](https://docs.ag-ui.com)
[![Tested with Strands Agents](https://img.shields.io/badge/tested%20with-Strands%20Agents%20(AWS)-FF9900?style=flat-square)](https://strandsagents.com)
[![uv](https://img.shields.io/badge/packaged%20with-uv-DE5FE9?style=flat-square)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/license-MIT-7BD88F?style=flat-square)](https://github.com/rahrajlat/Gentui/blob/main/LICENSE)
[![Status](https://img.shields.io/badge/status-alpha-F2C46D?style=flat-square)](#status)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-7BD88F?style=flat-square)](#contributing)
[![Stars](https://img.shields.io/github/stars/rahrajlat/Gentui?style=flat-square&color=4FD6C8)](https://github.com/rahrajlat/Gentui/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/rahrajlat/Gentui?style=flat-square&color=A78BFA)](https://github.com/rahrajlat/Gentui/commits/main)

</div>

---

## Get started

```bash
pip install gentui                               # or: uv tool install gentui
gentui http://localhost:8000/agent               # your AG-UI endpoint
```

Requires Python 3.12 or newer. Want to see it first? `gentui --demo` plays a tour of every feature with no backend
(pick a scene from the menu, or `gentui --demo approval`). No backend yet? See the [Quick start](#quick-start) for a sample agent.

## Why Gentui?

**Gentui is a terminal interface for prototyping agents really quickly.**

While developing agents locally, we end up spending our time on the frontend: a Streamlit or Chainlit
app, or a React project, just to talk to the agent. Each one is a separate frontend to build and keep
running, and it slows down the thing you actually want to iterate on: the agent.

Gentui removes that step. Install it, point it at your agent's AG-UI endpoint, and you get a chat, the
model's **chain of thought**, **human-in-the-loop (HITL)** and **approval** flows out of the box, with no
frontend code to write. Change your agent, restart it, and you're prototyping again in seconds.

When the agent calls a tool, the **tool call becomes the UI**: a command to approve, a table, a chart,
a live plan. Nothing risky runs until you click **Approve**.

**Tested with the [Strands Agents](https://strandsagents.com) framework (AWS's open-source agent SDK) over
AG-UI**: both on a custom backend (the [example backend](https://github.com/rahrajlat/Gentui/tree/main/examples/strands-backend)) and on the official
[`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter.

<div align="center">
<img src="https://raw.githubusercontent.com/rahrajlat/Gentui/main/docs/assets/tour.gif" alt="Gentui feature tour: AgentCore launch, slash commands, chain of thought, memory, plan, approval, output, table, chart, event inspector, themes" width="860">
</div>

## Features

- **Works with any AG-UI backend.** Streaming text, tool calls and shared state work out of the box;
  unknown tools show as a readable card, never an error.
- **Chain of thought, visible.** Reasoning streams into a collapsible "Thought for 3s" block.
- **Human-in-the-loop approval** built on AG-UI **interrupts**: the run ends waiting, your click
  `resume`s it. The model can't approve its own commands.
- **Generative widgets from tool calls:** command card, command output, tables, terminal charts
  (line, bar, scatter, histogram), live plan checklist.
- **Developer-friendly:** an event inspector (`/dev`) showing the raw SSE payloads exactly as sent, `/theme`,
  `/clear`, `/reasoning`, and a clear [backend contract](https://github.com/rahrajlat/Gentui/blob/main/docs/tool-contract.md).
- **Yours to customise:** TOML config, hot-reloaded CSS, your own themes, and Python plugins that add
  widgets, slash commands and event hooks.
- **Runs agents on AWS too:** invoke agents hosted on Amazon Bedrock AgentCore Runtime (AG-UI protocol) via boto3.
- **Backend-agnostic by design.** The client has no framework code; a complete example backend lives in
  [`examples/strands-backend`](https://github.com/rahrajlat/Gentui/tree/main/examples/strands-backend).

## The sample agent: natural language → shell

The command-approval flow in the tour above comes from the bundled example backend, a **natural-language-to-shell agent** built on Strands
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
conversations. It's a worked example of the [backend contract](https://github.com/rahrajlat/Gentui/blob/main/docs/tool-contract.md): copy it, or add your
own tools with [this guide](https://github.com/rahrajlat/Gentui/blob/main/examples/strands-backend/docs/add_a_tool.md).

## Quick start

Requires Python 3.12 or newer. Gentui is on [PyPI](https://pypi.org/project/gentui/):

```bash
pip install gentui                               # or: uv tool install gentui
gentui http://localhost:8000/agent               # your AG-UI endpoint
```

With [uv](https://docs.astral.sh/uv/) you can also run it without installing: `uvx gentui http://localhost:8000/agent`.

No backend yet? Run the [sample natural-language-to-shell agent](#the-sample-agent-natural-language--shell)
(Strands Agents + FastAPI). It lives in this repository, so clone it first, then start the backend in one terminal. It
uses a local [Ollama](https://ollama.com) by default; see its [README](https://github.com/rahrajlat/Gentui/blob/main/examples/strands-backend/README.md) for other providers:

```bash
git clone https://github.com/rahrajlat/Gentui.git
cd Gentui/examples/strands-backend
uv sync && cp .env.example .env
uv run server                                     # http://localhost:8000/agent
```

Then, in another terminal, start Gentui as above (`gentui http://localhost:8000/agent`).


Type `/help` to list the slash commands (`/new`, `/export_md`, `/theme`, `/dev`, `/reasoning`, `/quit`).
Working on Gentui itself? Run it from a clone with `uv sync` and `uv run gentui <url>`.

## Documentation

| I want to… | Read |
|---|---|
| use the slash commands, export a chat | [Slash commands](https://github.com/rahrajlat/Gentui/blob/main/docs/commands.md) |
| set options, themes, CSS, auth, map my own widgets | [Configuring and customising](https://github.com/rahrajlat/Gentui/blob/main/docs/customising.md) (all options: [`gentui.example.toml`](https://github.com/rahrajlat/Gentui/blob/main/gentui.example.toml)) |
| add widgets, commands or event hooks | [Plugins](https://github.com/rahrajlat/Gentui/blob/main/docs/plugins.md) |
| build my own backend in any language | [Backend contract](https://github.com/rahrajlat/Gentui/blob/main/docs/tool-contract.md) |
| talk to an agent on Amazon Bedrock AgentCore | [AgentCore Runtime](https://github.com/rahrajlat/Gentui/blob/main/docs/agentcore.md) |
| understand the internals | [How it works](https://github.com/rahrajlat/Gentui/blob/main/docs/architecture.md) |
| cut a release | [Releasing](https://github.com/rahrajlat/Gentui/blob/main/docs/releasing.md) |

### Example: an agent on AgentCore Runtime

Your runtime must be deployed with the AG-UI protocol. Then, end to end:

```bash
# 1. install with the optional AWS extra (adds boto3)
pip install "gentui[agentcore]"          # or: uv tool install "gentui[agentcore]"

# 2. log in with any normal AWS method
aws sso login --profile dev              # or export AWS_PROFILE / access keys

# 3. pass the runtime ARN instead of a URL
gentui arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my_agent-AbCdEfGhIj --profile dev
```

Optional flags: `--region eu-west-1` (default: the region in the ARN) and `--qualifier prod` (default: the
`DEFAULT` endpoint). Or put it in `gentui.toml` and just run `gentui`:

```toml
agentcore_arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my_agent-AbCdEfGhIj"
aws_profile = "dev"
send_history = true      # needed if the runtime rebuilds context from messages (e.g. ag-ui-strands)
```

The caller needs the `bedrock-agentcore:InvokeAgentRuntime` permission. IAM details, sessions and
troubleshooting are in the [AgentCore guide](https://github.com/rahrajlat/Gentui/blob/main/docs/agentcore.md).

## Status

Gentui is **alpha**. What has been verified, and what has not:

- Built and tested against the **Strands Agents** framework (AWS) over AG-UI: the
  [example backend](https://github.com/rahrajlat/Gentui/tree/main/examples/strands-backend) and the official
  [`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter (with `send_history = true`).
- AgentCore Runtime support works against a real runtime (confirmed by the author with a plain runtime ARN) and only
  covers runtimes using the AG-UI protocol. Other setups are covered by tests with a fake boto3 client and botocore's `Stubber`.
- Backends on other frameworks, the interrupt flow against a backend other than the example, other model
  providers than Ollama, and native Windows are **untested**.
- The look relies on Unicode box-drawing and block characters. If glyphs are missing, try a terminal
  font such as DejaVu Sans Mono, Cascadia or JetBrains Mono.

**Ideas, not built yet:** `show_form` / `ask_approval` tools, a composable JSON-tree UI tool, persistent
threads, record/replay of runs.

## Development

```bash
uv run pytest -q                                   # TUI tests: headless, no LLM or backend needed
cd examples/strands-backend && uv run pytest -q    # the example backend's own tests
```

The images above are generated from the app's own code:
`uv run --with pillow python docs/assets/build_assets.py` (logo, hero, `demo.gif`) and
`uv run --with pillow python docs/assets/build_tour.py` (the feature tour).

## Contributing

Issues and pull requests are welcome. Please run both test suites before opening a PR, and add a test
with any behaviour change. Because Gentui is a client for an open protocol, changes that keep it
backend-agnostic are the easiest to accept.

## License

[MIT](https://github.com/rahrajlat/Gentui/blob/main/LICENSE). Free to use, modify and distribute, including the [example backend](https://github.com/rahrajlat/Gentui/tree/main/examples/strands-backend).
