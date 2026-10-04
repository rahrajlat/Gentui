"""User configuration: where the backend is and how the UI looks.

Sources, lowest to highest priority:  defaults < config file < environment < CLI flags.

Config file (first found wins):  --config PATH, ./gentui.toml, ~/.config/gentui/config.toml
See `gentui.example.toml` for every option.
"""

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_WELCOME = (
    "Connected to {url}\n"
    "Type a message to talk to the agent.   /help for commands   [d] dev pane"
)


@dataclass
class Config:
    # -- backend -----------------------------------------------------------------------
    url: str = "http://localhost:8000/agent"  # any AG-UI endpoint
    headers: dict[str, str] = field(default_factory=dict)  # extra HTTP headers (auth etc.)
    token: str | None = None  # shortcut for "Authorization: Bearer <token>"
    forwarded_props: dict[str, Any] = field(default_factory=dict)  # sent with every run
    timeout: float | None = None  # seconds between bytes; None = wait forever (agents are slow)

    # -- look & feel -------------------------------------------------------------------
    title: str = "Gentui"
    subtitle: str = "Generative UI for your terminal"
    welcome: str = DEFAULT_WELCOME
    placeholder: str = "Ask anything…"
    theme: str = "tokyo-night"  # any Textual theme name; /theme lists them
    css: str | None = None  # your own Textual CSS file, hot-reloaded while the app runs
    show_reasoning: bool = True  # render the model's chain of thought
    dev_pane: bool = False  # start with the AG-UI event inspector open

    # -- extending ---------------------------------------------------------------------
    plugins: list[str] = field(default_factory=list)  # module names or .py paths to load
    widgets: dict[str, str] = field(default_factory=dict)  # tool name -> "module:Class"
    default_widget: str | None = None  # "module:Class" for tools without a widget

    source: Path | None = None  # the config file that was loaded (informational)

    @property
    def request_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        return headers

    @property
    def welcome_text(self) -> str:
        return self.welcome.replace("{url}", self.url)


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"config file not found: {path}")
        return path
    for path in (Path("gentui.toml"), Path.home() / ".config" / "gentui" / "config.toml"):
        if path.is_file():
            return path
    return None


def load_config(path: str | None = None, **overrides: Any) -> Config:
    """Build a Config. `overrides` (e.g. from CLI flags) win; None values are ignored."""
    cfg = Config()
    known = {f.name for f in fields(Config)} - {"source"}

    file = find_config(path)
    if file:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{file}: unknown option(s): {', '.join(sorted(unknown))}")
        for key, value in data.items():
            setattr(cfg, key, value)
        if cfg.css:  # relative CSS paths are relative to the config file
            cfg.css = str((file.parent / cfg.css).expanduser())
        cfg.source = file

    cfg.url = os.environ.get("GENTUI_URL", cfg.url)
    cfg.token = os.environ.get("GENTUI_TOKEN", cfg.token)

    for key, value in overrides.items():
        if value is not None:
            if key not in known:
                raise KeyError(key)
            setattr(cfg, key, value)
    return cfg
