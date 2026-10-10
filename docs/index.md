# Gentui

**A terminal interface for prototyping agents really quickly.** Point it at any [AG-UI](https://docs.ag-ui.com) backend and get
streaming chat, the model's chain of thought, tables, charts and human approval, with no frontend to build.

![Gentui feature tour](assets/tour.gif)

## Get started

```bash
pip install gentui                               # or: uv tool install gentui
gentui http://localhost:8000/agent               # your AG-UI endpoint
```

Requires Python 3.12 or newer. No backend yet? Try `gentui --demo`, which plays a tour of every feature by itself.

## What do you want to do?

| I want to | Read |
|---|---|
| see every command-line flag | [Command-line reference](cli.md) |
| use slash commands, themes and the event inspector | [Commands](commands.md) |
| save a session and play it back | [Record and replay](replay.md) |
| run the same prompts every time | [Run a set of prompts](prompts.md) |
| diff two runs of my agent side by side | [Compare runs](compare.md) |
| score how well two runs match, with my own judge model | [Judges](judges.md) |
| change colours, CSS and config | [Customising](customising.md) |
| add widgets, commands, event hooks or a judge | [Plugins](plugins.md) |
| build my own backend in any language | [Backend contract](tool-contract.md) |
| talk to an agent on Amazon Bedrock AgentCore | [AgentCore Runtime](agentcore.md) |
| understand the internals | [How it works](architecture.md) |
| cut a release | [Releasing](releasing.md) |

## Compare runs and judge them

Changed your agent's prompt or model? Run the same prompts against both versions and diff them side by side, with a
judge that scores the match for each prompt.

![Compare mode with a judge](assets/compare.gif)

[Compare runs](compare.md){ .md-button .md-button--primary } [Write a judge](judges.md){ .md-button }
