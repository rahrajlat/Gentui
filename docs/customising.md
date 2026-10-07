# Configuring and customising

## Configuration file

Put options in `./gentui.toml` or `~/.config/gentui/config.toml`. Flags, `GENTUI_URL` and `GENTUI_TOKEN`
override the file. Every option is documented in [`gentui.example.toml`](../gentui.example.toml): backend URL, token
and headers, props sent with every run, title, welcome text, theme, splash and logo, reasoning on/off, timestamps,
plugins and widget mapping.

> **Stateless backends** (ones that rebuild context from the message list, like the official
> `ag-ui-strands` adapter) need `send_history = true`. By default only the newest message is sent and
> the backend is expected to keep history per `threadId`.

## Command line

```bash
gentui https://my.host/agent --token sk-...        # bearer auth
gentui URL -H "X-Org: acme" --theme nord --dev     # extra header, theme, event inspector
```

## Themes

`theme = "nord"` in the config, or `/theme <name>` while running. The default is `gentui` (teal and violet);
`claude` (coral) is also built in.

## Your own styling

`css = "my.tcss"` loads a [Textual CSS](https://textual.textualize.io/guide/CSS/) file on top of the defaults and
**hot-reloads while the app runs**. Useful selectors: `.user`, `.assistant`, `.thinking`, `.error`, `ToolWidget`,
`#chat`, `#prompt`.

## Your own widget for a backend tool

Subclass `ToolWidget`, then map it without any plugin file:

```toml
[widgets]
show_map = "my_widgets:MapWidget"
```

For widgets, commands and event hooks together, write a [plugin](plugins.md).
