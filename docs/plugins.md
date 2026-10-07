# Plugins

A plugin is a plain Python file. Drop it in `./gentui_plugins/` or `~/.config/gentui/plugins/`, list it in
`plugins = [...]` or `--plugin`, or ship it as a pip package using the `gentui.plugins` entry point.

```python
from gentui.plugins import on_event, register_command
from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

@register_widget("weather")                  # render tool calls named "weather"
class Weather(ToolWidget):
    def on_end(self, args): self.show(f"☀ {args['city']}")

@register_command("ping", "say pong")        # adds /ping
def ping(app, args): app.notify("pong")

@on_event("TOOL_CALL_RESULT")                # hook any AG-UI event
async def audit(app, event): ...

def setup(app): ...                          # optional, runs once the app is mounted
```

## What a plugin can do

| Hook | Purpose |
|---|---|
| `@register_widget(tool_name)` | render a backend tool call with your own widget |
| `@register_command(name, help)` | add a slash command (shows up in `/help`) |
| `@on_event(EVENT_TYPE)` | run code for any AG-UI event |
| `setup(app)` | optional; runs once the app is mounted |

Plugins can mount any Textual widget into the conversation with `await app.mount_chat(widget)`. A
broken plugin is reported in a toast and never stops the app.

The API lives in [`plugins.py`](../src/gentui/plugins.py).
