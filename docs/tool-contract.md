# Backend contract

Gentui is a client for the [AG-UI protocol](https://docs.ag-ui.com). Anything an AG-UI backend
streams is shown with no setup (text, reasoning, tool calls as JSON cards, state, errors). This
page lists what a backend must do to get Gentui's **rich widgets**: the approval card, output,
table, chart, plan and memory line.

Nothing here is Strands-specific, and approval uses the protocol's own interrupts. The example backend in [`examples/strands-backend`](https://github.com/rahrajlat/Gentui/blob/main/examples/strands-backend) happens to use Strands; any language or
framework can follow the contract.

## 1. The request

Every user message is a `POST` of an AG-UI `RunAgentInput` to the endpoint, with
`accept: text/event-stream`:

| Field | What Gentui sends |
|---|---|
| `threadId` | one id per conversation; `/clear` starts a new one |
| `runId` | a new uuid per request |
| `messages` | **only the new user message** by default (empty when answering an interrupt). With `send_history = true`: the **whole conversation so far** (user, assistant, tool-call and tool messages, rebuilt from the events the backend streamed) |
| `state` | `{}` |
| `tools`, `context` | empty |
| `forwardedProps` | `{}` plus anything in the `forwarded_props` config option |
| `resume` | only when answering interrupts; see section 4 |

By default only the newest message is sent, so the backend must keep the conversation history per
`threadId`. A **stateless** backend, one that rebuilds its context from `messages` (the official
`ag-ui-strands` adapter is one), needs `send_history = true` in the config. Extra HTTP headers and the bearer token from the config are sent on every request.

The response is an SSE stream: one `data: <AG-UI event JSON>` line per event.

## 2. Events Gentui understands

| Event | Used for |
|---|---|
| `RUN_STARTED` / `RUN_FINISHED` / `RUN_ERROR` | run lifecycle; `RUN_ERROR` shows a red error box |
| `TEXT_MESSAGE_START` / `_CONTENT` / `_END` | streamed assistant text (Markdown) |
| `REASONING_START`, `REASONING_MESSAGE_START` / `_CONTENT` / `_END`, `REASONING_END` | chain of thought: a collapsible "Thinking…" block that collapses to "Thought" |
| `TOOL_CALL_START` / `_ARGS` / `_END` | picks a widget by `toolCallName`; the widget draws as the arguments stream in |
| `TOOL_CALL_RESULT` | the tool's result string, shown by the widget |
| `STATE_SNAPSHOT` / `STATE_DELTA` | shared state (JSON Patch for deltas); the `plan` key drives the plan widget |
| `RUN_FINISHED` with `outcome.type = "interrupt"` | the run is waiting for a decision; see section 4 |

Events it doesn't recognise are skipped, never fatal. Tool calls from **sub-agents** must be
forwarded to the client as ordinary top-level `TOOL_CALL_*` events for their widgets to appear.

## 3. Tool widgets

A tool gets a widget when its name matches. Any other name shows a generic JSON card (or your
`default_widget`). The widget is drawn from the tool call's **arguments**; they stream in as JSON
and are parsed once complete.

| Tool name | Arguments | Result (`TOOL_CALL_RESULT`) | Renders |
|---|---|---|---|
| `propose_command` | `command` (str), `explanation` (str), `risk`: `"safe"` \| `"caution"` \| `"dangerous"` | text; if it starts with `BLOCKED` the card shows a blocked state | command card with Approve / Edit / Reject |
| `run_command` | `approval_id` (str) | JSON `{"command", "exit_code", "timed_out", "truncated", "output"}`; any other text is shown as an error | output card with an exit-code badge |
| `show_table` | `title` (str), `columns` (list of str), `rows` (list of lists, first 100 shown) | ignored | table |
| `show_chart` | `type`: `"line"` \| `"bar"` \| `"scatter"` \| `"histogram"`, `title`, `x` (numbers or labels), `series`: `[{"name", "values": [numbers]}]`, optional `x_label`, `y_label`, `bins` | ignored | terminal chart. A bad spec shows a red message in the card |
| `todo_write` | anything | ignored | live plan checklist (see state below) |
| `search_memory` | `query` (str) | text; empty or `[]` is shown as "nothing remembered" | dim "🧠 recalled …" line |

### Plan state

The plan widget is drawn from shared state, not from the `todo_write` arguments. Emit state like:

```json
{"plan": [{"content": "check python version", "status": "completed"},
          {"content": "check disk usage", "status": "in_progress"}]}
```

`status` is `pending`, `in_progress` or `completed`. Send a `STATE_SNAPSHOT` first, then
`STATE_DELTA` JSON Patches. The widget is a single checklist, updated in place.

## 4. Approval: AG-UI interrupts

Approval uses the protocol's own human-in-the-loop mechanism
([AG-UI interrupts](https://docs.ag-ui.com/concepts/interrupts)): the run ends with an `interrupt`
outcome, and the client continues it with `resume`.

```
Run 1   user: "what are the 5 biggest files here?"
        backend: model calls propose_command({command, explanation, risk})
                 -> stream TOOL_CALL_START/ARGS/END (+ RESULT) for it
                 -> finish the run with an interrupt:
        {"type": "RUN_FINISHED", "threadId": "t", "runId": "r1",
         "outcome": {"type": "interrupt", "interrupts": [{
            "id": "approve-<toolCallId>",
            "reason": "tool_call",
            "toolCallId": "<id of the propose_command call>",
            "message": "Run this command?  ls -la",
            "responseSchema": {"type": "object",
               "properties": {"approved": {"type": "boolean"}, "command": {"type": "string"}},
               "required": ["approved"]}}]}}
        TUI:     the command card shows Approve / Edit / Reject.

Run 2   (same threadId, new runId, NO new message)
        {"threadId": "t", "runId": "r2", "messages": [],
         "resume": [{"interruptId": "approve-<toolCallId>",
                     "status": "resolved",                      # or "cancelled" for Reject
                     "payload": {"approved": true}}]}           # + "command" only if the user edited it
        backend: look up the command it recorded when it raised the interrupt, record the
                 approval, then let the model call run_command(approval_id) and execute it.
        TUI:     draws the output card from the run_command result.
```

How the TUI decides who answers: an interrupt with a `toolCallId` goes to the widget drawn for that
tool call (the command card). An interrupt with no matching widget gets a generic prompt showing
`message` with Approve / Reject (`{"approved": true|false}`), or only Cancel if `responseSchema`
asks for something other than `approved`. When several interrupts are open, the TUI sends **one**
`resume` that answers **all** of them, as the spec requires.

Rules a backend must follow for this to be safe:

1. **Remember the command yourself.** Store the proposed command against the interrupt id when you
   raise it. The client only says yes or no, and sends a command back only if the user edited it.
2. **Only run what a human approved.** `run_command` takes an id, never a command. An unknown or
   already-answered interrupt must be refused (the reference backend returns `RUN_ERROR`). One
   approval allows one run.
3. **End the run after proposing,** so the model cannot continue until the user decides.
4. **Treat an edited command as untrusted input** and re-check your safety policy at proposal, at
   approval and right before executing.
5. **A new user message abandons any open interrupt.** Don't let a stale approval run later.
6. **Limit execution:** timeout, output cap, a fixed working directory, and no stdin.

### Older backends (fallback)

A backend that never sends an interrupt still works: the card falls back to Gentui's earlier
handshake. A click sends the user message `Approved (approval_id=<toolCallId>). Call run_command
with this approval_id.` (or `Rejected. Do not run it.`) with
`forwardedProps = {"approval": {"decision": "approve"|"reject", "command": "...", "toolCallId": "..."}}`.
This is not part of AG-UI and the command comes from the client, so prefer interrupts for new backends.

If a backend has no `propose_command` tool, nothing breaks: its tool calls simply show as JSON
cards without buttons.

## Compatibility status

- **Tested end to end** with two Strands backends: the [example backend](https://github.com/rahrajlat/Gentui/blob/main/examples/strands-backend) in this repo (custom
  adapter) and the official [`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter serving
  a stock Strands agent. With the second (and `send_history = true`), streaming text, tool calls (as JSON cards), multi-turn
  context and error handling work, and the adapter's extra events (`MESSAGES_SNAPSHOT`, `RAW`) are
  skipped without trouble.
- **Not tested:** backends built on other frameworks, and the interrupt flow against a backend other
  than the reference one. Treat those as expected to work, not as verified.
- **Rich widgets** (approval, table, chart, plan) need the tool names and arguments in section 3.

## 5. Minimal checklist for a new backend

- [ ] Serve one `POST` endpoint that streams SSE AG-UI events.
- [ ] Keep history per `threadId` (only the newest message is sent), or tell users to set `send_history = true`.
- [ ] Emit `RUN_STARTED`, then text/tool events, then `RUN_FINISHED` (or `RUN_ERROR`).
- [ ] Name tools as in section 3 to get their widgets.
- [ ] To support approvals, implement section 4 (interrupt on `propose_command`, accept `resume`).
- [ ] Optional: `REASONING_*` events, and `STATE_SNAPSHOT` / `STATE_DELTA` for the plan.

To render a tool Gentui doesn't know, write a widget: see "Add features (plugins)" in the
[README](https://github.com/rahrajlat/Gentui/blob/main/README.md).
