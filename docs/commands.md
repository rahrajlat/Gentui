# Slash commands

Type these in the prompt. `/help` lists everything that is currently registered, including commands added by plugins.

| Command | Does |
|---|---|
| `/help` | list the available commands |
| `/new` | start a new chat (stops an answer that is still running; export first with `/export_md`) |
| `/clear` | same as `/new` |
| `/export_md [file or folder]` | save the chat as a Markdown file |
| `/theme [name]` | switch theme (no name lists the available themes) |
| `/dev` | toggle the AG-UI event inspector (`d` also works when the prompt is not focused) |
| `/reasoning` | show or hide the model's chain of thought |
| `/demo [scene]` | only with `gentui --demo`: play a scene (no name lists them) |
| `/quit` | exit |

Other keys: `Enter` sends the message.

## `/export_md`

Writes your messages, the agent's replies, its reasoning (when shown), tool calls with their results, and your
approve / reject decisions, in the order they happened.

- With no argument the file is `gentui-chat-<date>-<time>.md` in the current folder.
- An argument ending in `/` (or an existing folder) saves into that folder; otherwise it is used as the file name.
- It never overwrites an existing file; it adds `-1`, `-2`, … instead.

## Adding your own

Plugins can register commands with `@register_command`. See [plugins.md](plugins.md).

## Demo mode

`gentui --demo` needs no backend. It plays a scripted tour by itself: typing, approving a command, slash commands.

| Run | Plays |
|---|---|
| `gentui --demo` | a menu to choose from |
| `gentui --demo all` | the whole movie |
| `gentui --demo chat` / `approval` / `widgets` / `devtools` | one scene |
| `gentui --demo all --demo-speed 2` | twice as fast |

Inside the demo, `/demo <scene>` switches scene, and anything you type afterwards gets a canned reply.

## Record and replay

`gentui --record NAME` saves the session, `gentui --replay NAME` plays it back. See [replay.md](replay.md).
