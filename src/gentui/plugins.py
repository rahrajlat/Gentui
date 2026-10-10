"""Plugin API. A plugin is a plain Python file or module that imports these decorators.

    from gentui.plugins import register_command, on_event
    from gentui.tui.widgets.base import ToolWidget
    from gentui.tui.widgets.registry import register_widget

    @register_widget("weather")                 # render tool calls named "weather"
    class WeatherWidget(ToolWidget): ...

    @register_command("ping", "say pong")       # adds /ping
    def ping(app, args): app.notify("pong")

    @on_event("TOOL_CALL_RESULT")               # runs for every matching AG-UI event
    def log_results(app, event): ...

    @register_judge("mine")                     # a judge for `gentui --compare`: (case) -> {score, reason}
    async def mine(case): ...

    def setup(app): ...                         # optional; called once the app is mounted

Where plugins are loaded from: the `plugins = [...]` config option / `--plugin`,
`./gentui_plugins/*.py`, `~/.config/gentui/plugins/*.py`, and the `gentui.plugins`
entry-point group (for pip-installable plugins).
"""

import importlib
import importlib.metadata
import importlib.util
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

Command = Callable[[Any, str], Any]  # (app, argument string)
Hook = Callable[[Any, Any], Any]  # (app, ag_ui event)

COMMANDS: dict[str, tuple[Command, str]] = {}
HOOKS: list[tuple[frozenset[str] | None, Hook]] = []
SETUPS: list[Callable[[Any], Any]] = []
JUDGES: dict[str, Callable[[Any], Any]] = {}  # name -> judge(case); see gentui.judge


def register_command(name: str, help: str = "") -> Callable[[Command], Command]:
    def deco(fn: Command) -> Command:
        COMMANDS[name.lstrip("/")] = (fn, help)
        return fn

    return deco


def register_judge(name: str) -> Callable[[Callable[[Any], Any]], Callable[[Any], Any]]:
    """Add a judge for compare mode. It gets a `gentui.judge.Case` and returns {"score": 0..1, "reason": "..."}
    (a `Verdict`, or a (score, reason) tuple, also works). It may be sync or async."""

    def deco(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        JUDGES[name] = fn
        return fn

    return deco


def on_event(*types: str) -> Callable[[Hook], Hook]:
    """Hook called with (app, event). No types = every event. Types are EventType names."""

    def deco(fn: Hook) -> Hook:
        HOOKS.append((frozenset(types) or None, fn))
        return fn

    return deco


async def call(fn: Callable[..., Any], *args: Any) -> Any:
    result = fn(*args)
    return await result if inspect.isawaitable(result) else result


async def dispatch_event(app: Any, event: Any) -> None:
    kind = event.type.value
    for types, hook in HOOKS:
        if types is None or kind in types:
            try:
                await call(hook, app, event)
            except Exception as exc:  # noqa: BLE001 - a broken plugin must not kill the UI
                app.notify(f"plugin hook {hook.__name__} failed: {exc!r}", severity="error")


def import_string(spec: str) -> Any:
    """'package.module:Name' -> the object."""
    module, _, name = spec.partition(":")
    if not name:
        raise ValueError(f"expected 'module:Name', got {spec!r}")
    return getattr(importlib.import_module(module), name)


def _load_file(path: Path) -> None:
    name = f"gentui_plugin_{path.stem}"
    if name in sys.modules:  # already loaded (e.g. several apps in one process)
        return
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load plugin {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _register_setup(module)


def _register_setup(module: Any) -> None:
    setup = getattr(module, "setup", None)
    if callable(setup) and setup not in SETUPS:
        SETUPS.append(setup)


def load_plugin(spec: str) -> None:
    """Load one plugin: a .py file, a directory of .py files, or an importable module."""
    path = Path(spec).expanduser()
    if path.is_dir():
        for file in sorted(path.glob("*.py")):
            if not file.name.startswith("_"):
                _load_file(file)
    elif path.suffix == ".py":
        _load_file(path)
    else:
        _register_setup(importlib.import_module(spec))


def load_all(extra: list[str], widgets: dict[str, str], default_widget: str | None) -> list[str]:
    """Load every plugin source and apply config widget overrides. Returns error messages."""
    from gentui.tui.widgets.registry import register_widget, set_default_widget

    errors: list[str] = []

    def attempt(label: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report, keep starting
            errors.append(f"{label}: {exc!r}")

    for ep in importlib.metadata.entry_points(group="gentui.plugins"):
        attempt(f"plugin {ep.name}", lambda ep=ep: _register_setup(ep.load()))  # importing registers
    for folder in (Path.home() / ".config" / "gentui" / "plugins", Path("gentui_plugins")):
        if folder.is_dir():
            attempt(f"plugins in {folder}", lambda folder=folder: load_plugin(str(folder)))
    for spec in extra:
        attempt(f"plugin {spec}", lambda spec=spec: load_plugin(spec))
    for tool, spec in widgets.items():
        attempt(f"widget {tool}", lambda tool=tool, spec=spec: register_widget(tool)(import_string(spec)))
    if default_widget:
        attempt("default_widget", lambda: set_default_widget(import_string(default_widget)))
    return errors
