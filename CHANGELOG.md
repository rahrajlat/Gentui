# Changelog

All notable changes to Gentui are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/)
(while below 1.0, minor versions may change behaviour).

## [Unreleased]

### Added
- `gentui --demo [scene]` plays a scripted tour of every feature, like a movie, with no backend: it types, approves a
  command and runs slash commands by itself. Scenes: `all`, `chat`, `approval`, `widgets`, `devtools`. A bare `--demo`
  shows a menu; `/demo <scene>` switches scene inside the app; `--demo-speed X` changes the pace.
- `/new` starts a new chat. A run still in flight is stopped first, so the old answer cannot stream into the new chat.
- `/export_md [file or folder]` saves the conversation as Markdown: messages, replies, reasoning, tool calls and results, and
  approve / reject decisions. `show_table` calls become Markdown tables. Existing files are never overwritten.

### Changed
- `/clear` is now an alias of `/new` and also stops a run in flight.
- The `Ctrl+Q` and `Ctrl+D` shortcuts are removed. Use the slash commands `/quit` and `/dev` instead. (`Ctrl+C` now
  tells you to type `/quit`.)

## [0.1.0] - 2026-10-05

First public release (alpha).

### Added
- Terminal client for [AG-UI](https://docs.ag-ui.com) agent backends: streaming chat, tool calls, shared state and errors.
- The model's chain of thought as a collapsible "Thought for Ns" block (`REASONING_*` events).
- Human-in-the-loop approval built on AG-UI interrupts: a run ends with an `interrupt` outcome and the Approve / Edit /
  Reject buttons `resume` it. A generic prompt handles interrupts no tool widget claims.
- Widgets drawn from tool calls: command card, command output, table, terminal charts (line, bar, scatter, histogram),
  live plan checklist, memory lookups.
- Support for agents hosted on **Amazon Bedrock AgentCore Runtime** (AG-UI protocol) through boto3, including endpoint
  ARNs (`.../runtime-endpoint/<name>`). boto3 is an optional extra: `gentui[agentcore]`.
- Configuration (`gentui.toml`, flags, environment variables), themes, hot-reloaded CSS, and a plugin API for widgets,
  slash commands and event hooks.
- Animated startup splash, a static logo, timestamps, an event inspector showing raw SSE payloads (`d`), slash commands
  (`/help`, `/theme`, `/clear`, `/reasoning`, `/dev`, `/quit`) and `gentui --version`.
- `send_history` option for stateless backends (such as the official `ag-ui-strands` adapter).
- An example backend, a natural-language-to-shell agent on Strands Agents, in `examples/strands-backend`
  (a separate project with its own dependencies).
- A [backend contract](docs/tool-contract.md) describing the request, the events and the tool names that get widgets.

### Known limitations
- Tested against Strands Agents backends and AgentCore Runtime only. Other frameworks, other model providers than Ollama
  and native Windows are untested.
- AgentCore runtimes that use the HTTP protocol, MCP or A2A (instead of AG-UI) are not supported.

[0.1.0]: https://github.com/rahrajlat/Gentui/releases/tag/v0.1.0
