# Command-line reference

```text
gentui [URL|ARN] [options]
```

Options can also live in `gentui.toml` ([customising](customising.md)). Run `gentui --help` for the same list.

## Connecting

| Flag | Does |
|---|---|
| `URL` or `--url URL` | AG-UI endpoint (default `http://localhost:8000/agent`) |
| `--agentcore-arn ARN` | an agent on Amazon Bedrock AgentCore Runtime ([AgentCore](agentcore.md)) |
| `--region`, `--profile`, `--qualifier` | AgentCore region, AWS profile and endpoint name |
| `--token TOKEN` | send `Authorization: Bearer <token>` (or set `GENTUI_TOKEN`) |
| `--header`, `-H 'Name: value'` | an extra HTTP header (repeatable) |

## Look and behaviour

| Flag | Does |
|---|---|
| `--config`, `-c FILE` | config file (default `./gentui.toml`) |
| `--theme NAME` | Textual theme |
| `--css FILE` | your own CSS, hot-reloaded |
| `--plugin`, `-p MODULE\|FILE` | load a [plugin](plugins.md) (repeatable) |
| `--no-reasoning` | hide the model's chain of thought |
| `--dev` | open the AG-UI event inspector at start |
| `--version` | print the version |

## Demo, record and replay

| Flag | Does |
|---|---|
| `--demo [SCENE]` | play a scripted tour with no backend: `all`, `chat`, `approval`, `widgets`, `devtools` (no name = a menu) |
| `--demo-speed X` | demo playback speed |
| `--record NAME` | save the session to `NAME.json` ([Record and replay](replay.md)) |
| `--replay NAME` | play `NAME.json` back, no backend needed |

## Prompts, compare, judge and export

| Flag | Does |
|---|---|
| `--prompts FILE` | send the prompts in a YAML file one after the other ([Run a set of prompts](prompts.md)) |
| `--compare NAME,NAME,...` | diff recorded sessions side by side, no backend needed ([Compare runs](compare.md)) |
| `--judge NAME` | with `--compare`: score each prompt with this judge ([Judges](judges.md)) |
| `--export FILE.html` | with `--compare`: write the comparison, every chart included, to an HTML page |

## Which flags go together

- `--record` works with a URL, an ARN or `--demo`; it cannot be combined with `--replay`.
- `--prompts` needs a live backend, so not with `--replay` or `--demo`. It combines with `--record`.
- `--compare` stands alone. `--judge` and `--export` only work with it.
