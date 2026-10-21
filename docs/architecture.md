# How it works

```
 gentui (Textual) ── POST /agent (RunAgentInput) ──▶ any AG-UI backend
      ▲                                                    │
      │◀────────────── SSE: AG-UI events ─────────────────┘

 Approve ▸ `resume` of the run's interrupt ──▶ backend runs the approved command
```

Without a server, an adapter stands in for the HTTP client: it runs your Strands or LangChain agent in the same process
and yields the same AG-UI events, so everything after it is unchanged.

```
 gentui (Textual) ── adapter.run(...) ──▶ your agent, in this process
      ▲                                           │
      │◀──────── AG-UI events (translated) ───────┘
```

| Piece | File |
|---|---|
| SSE client (RunAgentInput in, typed events out) | [`tui/agui_client.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/tui/agui_client.py) |
| In-process adapters (Strands, LangChain / LangGraph) | [`adapters/`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/adapters) |
| Event → widget dispatch, interrupts, chat | [`tui/app.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/tui/app.py) |
| Widgets and the tool-name registry | [`tui/widgets/`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/tui/widgets) |
| Built-in slash commands | [`tui/commands.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/tui/commands.py) |
| Logo, splash and animation | [`tui/branding.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/tui/branding.py), [`tui/splash.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/tui/splash.py) |
| Plugin API and config | [`plugins.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/plugins.py), [`config.py`](https://github.com/rahrajlat/Gentui/blob/main/src/gentui/config.py) |

AG-UI events used: `RUN_STARTED/FINISHED/ERROR` (with `outcome: interrupt`), `TEXT_MESSAGE_*`,
`REASONING_*`, `TOOL_CALL_START/ARGS/END/RESULT`, `STATE_SNAPSHOT`, `STATE_DELTA`. The request side
uses `messages`, `forwardedProps` and `resume`.

`gentui --serve` wraps all of this in [textual-serve](https://github.com/Textualize/textual-serve): the same command runs
once per browser tab and the page shows its terminal.

For the backend side, see the [backend contract](tool-contract.md).
