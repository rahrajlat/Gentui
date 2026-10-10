# Record and replay

```bash
gentui http://localhost:8000/agent --record my_session   # chat as usual; quit when done
gentui --replay my_session                               # no backend needed
```

`--record NAME` works with any backend (a URL, an AgentCore ARN, or `--demo`). `NAME` becomes `NAME.json` in the current
folder (`--record runs/monday` writes `runs/monday.json`, and the folder must exist). Gentui refuses to overwrite a file
that is already there. The file is saved after every run and again when you quit.

## Controls

| Key / mouse | Does |
|---|---|
| `space` or the **Pause / Play** button | pause and play (at the end, it plays again from the start) |
| drag or click the bar | seek to any moment, forwards or back. `◆` marks where you sent a message |
| `←` / `→` | jump 5 seconds back / forward |
| `home` | back to the start |
| `+` / `-` or the speed button | 0.5x, 1x, 2x, 4x, 8x |
| `t` or click a "Thought for 3s" block | open or close the chain of thought. `t` toggles all of them |
| `d` | show the raw AG-UI events |
| `q` | quit |

Seeking backwards clears the chat and replays everything up to that moment, so it always matches what you saw live.
Anything you opened or closed by hand is reset when you seek.

## What is drawn

The replay feeds the recorded events to the same code that draws a live chat, so you get streamed Markdown, the chain of
thought, every tool widget (commands and their output, tables, charts, the plan, memory lines, unknown tools as JSON cards)
and the approval cards, which show the decision that was made (Approved, Approved with an edited command, Rejected). The
buttons are disabled: a replay never sends anything.

Waits longer than 1.5 seconds (you thinking, a slow model) are squeezed to 1.5 seconds on the timeline, so a replay never
sits idle. "Thought for Ns" and the time beside each message show the recorded time.

## The file

```json
{"format": "gentui-session", "version": 1, "gentui": "0.1.2", "recorded_at": "2026-10-09T10:15:00+01:00",
 "target": "http://localhost:8000/agent",
 "items": [
  {"t": 0.0,  "kind": "user",   "text": "what are the 5 largest files here?"},
  {"t": 0.41, "kind": "event",  "event": {"type": "RUN_STARTED", "threadId": "...", "runId": "..."}},
  {"t": 3.2,  "kind": "resume", "entries": [{"interruptId": "approve-c1", "status": "resolved", "payload": {"approved": true}}]}
 ]}
```

`t` is seconds since the recording started. `kind` is `user` (a message you sent), `event` (an AG-UI event exactly as the
backend sent it), `resume` (your answer to an interrupt), `submit` (a widget's message on older backends) or `new` (`/new`).

**Treat a recording like a log.** It holds whatever the agent streamed, including tool output, so it can contain secrets
or private data. Headers, tokens and your config are never written. Share recordings with care.

## Run a set of prompts: `--prompts`

Put the messages in a YAML file and Gentui sends them for you, one after the other, each when the previous answer is
complete:

```yaml
# prompts.yml
prompts:
  - What are the 5 largest files here?
  - text: Now plot them as a bar chart
```

```bash
gentui http://localhost:8000/agent --prompts prompts.yml --record baseline
```

A bare list works too, and each item is a string or a mapping with a `text` key. Combined with `--record` this gives you a
repeatable run you can keep. If the agent asks for approval, the queue waits for your answer. When the last prompt has been
answered the app stays open (type `/quit` to leave), so you can carry on the conversation by hand.

## Compare runs: `--compare`

Record the same prompts against two versions of an agent (a new system prompt, a different model), then diff them:

```bash
gentui URL --prompts prompts.yml --record v1
gentui URL --prompts prompts.yml --record v2      # after changing the agent
gentui --compare v1,v2                            # no backend needed
```

`--compare` takes two or more recorded sessions. It opens a view with two boxes, each with a drop-down to choose which
recording it shows (list as many as you like and switch between them). The two are lined up block by block (your prompts,
each answer, each tool call) and drawn in full: streamed Markdown, command output, tables, charts and the plan.

| Colour | Meaning |
|---|---|
| green bar and tint | only in the right-hand session |
| red bar and tint | only in the left-hand session |
| yellow bar and tint | in both, but different (a changed answer, other arguments, another tool result) |
| none | identical |

A third drop-down, "All prompts", lists each prompt from the prompts file ("1. What are the 5 largest…"). Pick one to see only
that prompt's exchange, side by side.

Changed answers and prompts are shown word by word (red words are only on the left, green only on the right). Press `m` to
switch them to the rendered Markdown instead. A line under the drop-downs counts same / changed / only-in-each. Reasoning
blocks are shown but never counted as a difference. `q` quits.
