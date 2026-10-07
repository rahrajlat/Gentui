"""User configuration: where the backend is and how the UI looks.

Sources, lowest to highest priority:  defaults < config file < environment < CLI flags.

Config file (first found wins):  --config PATH, ./gentui.toml, ~/.config/gentui/config.toml
See `gentui.example.toml` for every option.
"""

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_WELCOME = (
    "◈ Welcome to Gentui!\n\n"
    "  /help for commands · /quit to exit · /dev for the event inspector\n"
    "  backend: {url}\n"
    "  cwd: {cwd}"
)


_RUNTIME_ARN = re.compile(
    r"^(?P<runtime>arn:aws[a-z-]*:bedrock-agentcore:(?P<region>[a-z0-9-]+):(?P<account>\d{12}):runtime/[^/\s]+)"
    r"(?:/runtime-endpoint/(?P<endpoint>[^/\s]+))?$"
)


def _match_runtime_arn(arn: str) -> re.Match[str]:
    match = _RUNTIME_ARN.match(arn.strip())
    if not match:
        raise ValueError(
            f"not an AgentCore runtime ARN: {arn!r} "
            "(expected arn:aws:bedrock-agentcore:<region>:<account>:runtime/<name>"
            "[/runtime-endpoint/<endpoint>])"
        )
    return match


def parse_runtime_arn(arn: str) -> tuple[str, str]:
    """(region, account id) of an AgentCore runtime ARN. Raises ValueError for anything else."""
    match = _match_runtime_arn(arn)
    return match["region"], match["account"]


def split_runtime_arn(arn: str) -> tuple[str, str | None]:
    """(runtime ARN, endpoint name). An endpoint ARN (`.../runtime/<name>/runtime-endpoint/<endpoint>`) is
    accepted: invoke_agent_runtime wants the plain runtime ARN, with the endpoint passed as its qualifier."""
    match = _match_runtime_arn(arn)
    return match["runtime"], match["endpoint"]


@dataclass
class Config:
    # -- backend -----------------------------------------------------------------------
    url: str = "http://localhost:8000/agent"  # any AG-UI endpoint
    # An agent hosted on Amazon Bedrock AgentCore Runtime (AG-UI protocol), invoked with boto3.
    # When set it is used instead of `url`. Needs the optional dependency: gentui[agentcore].
    agentcore_arn: str | None = None
    region: str | None = None  # default: the region in the ARN
    aws_profile: str | None = None  # default: the standard AWS credential chain
    qualifier: str | None = None  # runtime endpoint name; default: the runtime's DEFAULT endpoint
    headers: dict[str, str] = field(default_factory=dict)  # extra HTTP headers (auth etc.)
    token: str | None = None  # shortcut for "Authorization: Bearer <token>"
    forwarded_props: dict[str, Any] = field(default_factory=dict)  # sent with every run
    send_history: bool = False  # True: send the whole conversation each run (stateless backends need it)
    timeout: float | None = None  # seconds between bytes; None = wait forever (agents are slow)

    # -- look & feel -------------------------------------------------------------------
    title: str = "Gentui"
    subtitle: str = "Generative UI for your terminal"
    welcome: str = DEFAULT_WELCOME
    placeholder: str = "Ask anything…"
    theme: str = "gentui"  # "gentui", "claude" or any Textual theme name; /theme lists them
    splash: bool = True  # animated logo on startup (any key skips it)
    logo: bool = True  # keep the finished logo at the top of the chat after the splash
    show_time: bool = True  # a timestamp on every message
    time_format: str = "%H:%M"  # strftime format for those timestamps
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
    def target(self) -> str:
        """What the client talks to: the AgentCore runtime ARN, or the URL."""
        return self.agentcore_arn or self.url

    @property
    def welcome_text(self) -> str:
        return self.welcome.replace("{url}", self.target).replace("{cwd}", os.getcwd())


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
    cfg.agentcore_arn = os.environ.get("GENTUI_AGENTCORE_ARN", cfg.agentcore_arn)

    for key, value in overrides.items():
        if value is not None:
            if key not in known:
                raise KeyError(key)
            setattr(cfg, key, value)
    if cfg.agentcore_arn:
        parse_runtime_arn(cfg.agentcore_arn)  # fail early with a clear message
    return cfg
