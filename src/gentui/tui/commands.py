"""Built-in slash commands. Plugins add more with `gentui.plugins.register_command`."""

from datetime import datetime
from pathlib import Path

from textual.widgets import Static

from gentui.plugins import COMMANDS, register_command


@register_command("help", "list the available commands")
async def help_(app, args: str) -> None:
    lines = [f"/{name:<10} {help_text}" for name, (_, help_text) in sorted(COMMANDS.items())]
    await app.mount_chat(Static("\n".join(lines), classes="welcome"))


@register_command("new", "start a new chat (stops a running answer; export first with /export_md)")
async def new(app, args: str) -> None:
    await app.new_thread()
    app.notify("New chat started")


@register_command("clear", "same as /new")
async def clear(app, args: str) -> None:
    await app.new_thread()


def export_path(arg: str, now: datetime | None = None) -> Path:
    """Where /export_md writes. No argument: a timestamped file in the current folder. A folder: a timestamped
    file in it. Anything else: that file, with .md added when it has no extension."""
    name = f"gentui-chat-{(now or datetime.now()):%Y%m%d-%H%M%S}.md"
    arg = arg.strip().strip("\"'")
    if not arg:
        return Path.cwd() / name
    path = Path(arg).expanduser()
    if arg.endswith(("/", "\\")) or path.is_dir():
        return path / name
    return path if path.suffix else path.with_suffix(".md")


@register_command("export_md", "save the chat as a Markdown file: /export_md [file or folder]")
async def export_md(app, args: str) -> None:
    if not app.transcript:
        app.notify("Nothing to export yet: the conversation is empty", severity="warning")
        return
    try:
        saved = app.transcript.save(
            export_path(args),
            backend=app.config.target,
            thread_id=app.thread_id,
            time_format=app.config.time_format,
        )
    except OSError as exc:
        app.notify(f"Could not export: {exc}", severity="error", timeout=10)
        return
    app.notify(f"Chat exported to {saved}", timeout=10)
    await app.mount_chat(Static(f"Exported this chat to {saved}", classes="welcome"))


@register_command("theme", "switch theme: /theme <name>  (no name = list them)")
async def theme(app, args: str) -> None:
    name = args.strip()
    if not name:
        await app.mount_chat(Static("themes: " + ", ".join(sorted(app.available_themes)), classes="welcome"))
    elif name in app.available_themes:
        app.theme = name
    else:
        app.notify(f"unknown theme {name!r}", severity="warning")


@register_command("dev", "toggle the AG-UI event inspector")
def dev(app, args: str) -> None:
    app.action_toggle_dev()


@register_command("reasoning", "show/hide the model's chain of thought")
def reasoning(app, args: str) -> None:
    app.show_reasoning = not app.show_reasoning
    app.notify("reasoning " + ("shown" if app.show_reasoning else "hidden"))


@register_command("quit", "exit")
def quit_(app, args: str) -> None:
    app.exit()
