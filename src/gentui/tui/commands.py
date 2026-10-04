"""Built-in slash commands. Plugins add more with `gentui.plugins.register_command`."""

from textual.widgets import Static

from gentui.plugins import COMMANDS, register_command


@register_command("help", "list the available commands")
async def help_(app, args: str) -> None:
    lines = [f"/{name:<10} {help_text}" for name, (_, help_text) in sorted(COMMANDS.items())]
    await app.mount_chat(Static("\n".join(lines), classes="welcome"))


@register_command("clear", "clear the screen and start a new conversation")
async def clear(app, args: str) -> None:
    await app.new_thread()


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
