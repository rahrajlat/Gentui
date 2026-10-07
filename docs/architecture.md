# How it works

```
 gentui (Textual) ── POST /agent (RunAgentInput) ──▶ any AG-UI backend
      ▲                                                    │
      │◀────────────── SSE: AG-UI events ─────────────────┘

 Approve ▸ `resume` of the run's interrupt ──▶ backend runs the approved command
```

| Piece | File |
|---|---|
| SSE client (RunAgentInput in, typed events out) | [`tui/agui_client.py`](../src/gentui/tui/agui_client.py) |
| Event → widget dispatch, interrupts, chat | [`tui/app.py`](../src/gentui/tui/app.py) |
| Widgets and the tool-name registry | [`tui/widgets/`](../src/gentui/tui/widgets) |
| Built-in slash commands | [`tui/commands.py`](../src/gentui/tui/commands.py) |
| Logo, splash and animation | [`tui/branding.py`](../src/gentui/tui/branding.py), [`tui/splash.py`](../src/gentui/tui/splash.py) |
| Plugin API and config | [`plugins.py`](../src/gentui/plugins.py), [`config.py`](../src/gentui/config.py) |

AG-UI events used: `RUN_STARTED/FINISHED/ERROR` (with `outcome: interrupt`), `TEXT_MESSAGE_*`,
`REASONING_*`, `TOOL_CALL_START/ARGS/END/RESULT`, `STATE_SNAPSHOT`, `STATE_DELTA`. The request side
uses `messages`, `forwardedProps` and `resume`.

For the backend side, see the [backend contract](tool-contract.md).
