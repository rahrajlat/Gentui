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
