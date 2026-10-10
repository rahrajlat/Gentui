<div align="center">

<img src="https://raw.githubusercontent.com/rahrajlat/Gentui/main/docs/assets/hero.gif" alt="Gentui: generative UI for your terminal" width="640">

**A terminal interface for prototyping agents really quickly.**<br>
Point it at any [AG-UI](https://docs.ag-ui.com) backend and get streaming chat, the model's chain of thought,<br>
tables, charts and human approval, with no frontend to build.

[![CI](https://img.shields.io/github/actions/workflow/status/rahrajlat/Gentui/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/rahrajlat/Gentui/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-rahrajlat.github.io%2FGentui-4FD6C8?style=flat-square)](https://rahrajlat.github.io/Gentui/)
[![PyPI](https://img.shields.io/pypi/v/gentui?style=flat-square&color=4FD6C8)](https://pypi.org/project/gentui/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/gentui?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/gentui)
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
gentui --demo                                    # no backend yet? watch a tour of every feature
```

Requires Python 3.12 or newer.

## Documentation

**Full docs, with search: [rahrajlat.github.io/Gentui](https://rahrajlat.github.io/Gentui/)**

| I want to… | Read |
|---|---|
| install it and try the demo | [Getting started](https://rahrajlat.github.io/Gentui/getting-started/) |
| see every command-line flag | [Command-line reference](https://rahrajlat.github.io/Gentui/cli/) |
| use slash commands, themes and the event inspector | [Commands](https://rahrajlat.github.io/Gentui/commands/) |
| save a session and play it back | [Record and replay](https://rahrajlat.github.io/Gentui/replay/) |
| run the same prompts every time | [Run a set of prompts](https://rahrajlat.github.io/Gentui/prompts/) |
| diff two runs side by side | [Compare runs](https://rahrajlat.github.io/Gentui/compare/) |
| score runs with my own judge model | [Judges](https://rahrajlat.github.io/Gentui/judges/) |
| change config, CSS and colours | [Customising](https://rahrajlat.github.io/Gentui/customising/) |
| add widgets, commands or event hooks | [Plugins](https://rahrajlat.github.io/Gentui/plugins/) |
| build my own backend in any language | [Backend contract](https://rahrajlat.github.io/Gentui/tool-contract/) |
| talk to an agent on Amazon Bedrock AgentCore | [AgentCore Runtime](https://rahrajlat.github.io/Gentui/agentcore/) |
| understand the internals | [How it works](https://rahrajlat.github.io/Gentui/architecture/) |

## See it

<div align="center">
<img src="https://raw.githubusercontent.com/rahrajlat/Gentui/main/docs/assets/tour.gif" alt="Gentui feature tour: AgentCore launch, slash commands, chain of thought, memory, plan, approval, output, table, chart, event inspector, themes" width="860">
</div>

### Record and replay

Save any session to JSON, then play it back with pause, a seek bar and speed control. No agent, no network. [Read more](https://rahrajlat.github.io/Gentui/replay/)

<div align="center">
<img src="https://raw.githubusercontent.com/rahrajlat/Gentui/main/docs/assets/replay.gif" alt="Gentui replay: play, pause, rewind with the seek bar, open the chain of thought, charts and approvals drawn as they were live" width="860">
</div>

### Compare runs and judge them

Run the same prompts against two versions of your agent, diff the results side by side, and let a judge (Ollama built in, or your own function) score each prompt. Export it all, charts included, to one HTML page. [Read more](https://rahrajlat.github.io/Gentui/compare/)

<div align="center">
<img src="https://raw.githubusercontent.com/rahrajlat/Gentui/main/docs/assets/compare.gif" alt="Gentui compare mode: two runs side by side as a diff, a prompt picker, and a judge panel with a match score and comment for each prompt" width="860">
</div>

## Status

Gentui is **alpha**: tested with the Strands Agents framework over AG-UI and with AgentCore Runtime; other setups are untested. The details are in [Development and status](https://rahrajlat.github.io/Gentui/development/).

## Contributing

Issues and pull requests are welcome. Please run the tests (`uv run pytest -q`) before opening a PR, and add a test with any behaviour change. See [Development and status](https://rahrajlat.github.io/Gentui/development/).

## License

[MIT](https://github.com/rahrajlat/Gentui/blob/main/LICENSE). Free to use, modify and distribute, including the [example backend](https://github.com/rahrajlat/Gentui/tree/main/examples/strands-backend).
