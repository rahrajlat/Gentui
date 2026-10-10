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

## Score the match with a judge

In the compare view, the **Judge** drop-down turns a judge on. Each prompt's section then opens with a boxed **Judge panel**: a match score
(0 to 100%) with a bar, and the judge's comment on the key difference. The box is green from 80%, yellow from 50% and red
below; the summary shows the average. Prompts whose answers and tool calls are
identical score 100% without calling the judge. `--judge NAME` switches one on at start.

Gentui ships a judge for [Ollama](https://ollama.com), named `ollama:<model>`. Any model works after the colon:

```bash
# a "-cloud" model goes through your local Ollama, which forwards it to Ollama Cloud (run `ollama signin` once, no key)
gentui --compare v1,v2 --judge ollama:gpt-oss:120b-cloud

# straight to ollama.com with an API key (ollama.com/settings/keys); default model gpt-oss:120b
export OLLAMA_API_KEY=...
gentui --compare v1,v2 --judge ollama
GENTUI_JUDGE_MODEL=deepseek-v3.1:671b gentui --compare v1,v2 --judge ollama

# a model on your local Ollama needs no key
gentui --compare v1,v2 --judge ollama:qwen3:8b
```

`OLLAMA_HOST` points it at another server (it overrides the above).

To bring your own judge, write a plugin and load it with `--plugin`:

```python
# my_judge.py
from gentui.plugins import register_judge

@register_judge("mine")
async def mine(case):          # sync works too
    # case.prompt, case.left, case.right (the answers as text),
    # case.left_tools, case.right_tools ([{"name", "args", "result"}])
    return {"score": 0.8, "reason": "same facts, B leaves out the disk threshold"}
```

```bash
gentui --compare v1,v2 --plugin my_judge.py --judge mine
```

Return `{"score": 0..1, "reason": "..."}` (or a `(score, reason)` tuple). A judge that raises shows "judge failed" on that
prompt and nothing else is affected. Verdicts are cached in `~/.cache/gentui/judge.json`, keyed by the judge and both
answers, so judging the same pair again is instant and free.

**Privacy:** a judge is sent the prompt, the answers and the tool output. With a hosted judge that leaves your machine, and
recordings can contain secrets. Judging only happens when you turn a judge on.

## Export the results

Press **`e`** in the compare view to save the comparison as one HTML page, `compare-<left>-vs-<right>.html` in the current
folder (an existing file is never overwritten: you get `-1`, `-2`...). Without opening the UI:

```bash
gentui --compare v1,v2 --export report.html                       # the diff only
gentui --compare v1,v2 --judge ollama:gpt-oss:120b-cloud --export report.html   # judge every prompt first
```

The page shows what the compare view shows, for **all** prompts: the judge's panel (score, bar and comment) on top of each
prompt, then both sides' answers, tool calls, tables, command output and plans. **Every chart is included**, drawn as inline
SVG (bar, line, scatter and histogram). Changed blocks are tinted (green only on the right, red only on the left, yellow changed),
and changed text is marked word by word, with the rendered Markdown a click away. It is a single file with no scripts and
nothing loaded from the web, follows your light or dark setting, stacks on a phone and prints cleanly. Anything in an answer
that looks like HTML is escaped, never run.

Pressing `e` while a judge is still working exports the verdicts that have arrived; the notice says so. `--export` waits for
all of them.
