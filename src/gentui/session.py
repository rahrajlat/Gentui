"""Recording a session to a JSON file, and loading one back for `--replay`.

A session file holds what you typed and every AG-UI event the backend streamed, each with the seconds since the
recording started. It never holds headers, tokens or config. The events are exactly what the agent sent, so a file can
contain whatever the agent said, including secrets in tool output: treat it like a log.
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ag_ui.core import BaseEvent, Event
from pydantic import TypeAdapter, ValidationError

FORMAT = "gentui-session"
VERSION = 1
IDLE_CAP = 1.5  # replay squeezes any wait longer than this (you thinking, a slow model) down to this many seconds

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)

# what an item can be: you sent a message / the backend sent an event / you answered interrupts /
# a widget sent a message for you (older backends) / you started a new chat
KINDS = ("user", "event", "resume", "submit", "new")


class SessionError(Exception):
    """A session file that cannot be written or read. The message is safe to show the user."""


def resolve(name: str) -> Path:
    """`demo` -> ./demo.json; a path keeps its folder; `.json` is added when there is no extension."""
    path = Path(name).expanduser()
    return path if path.suffix else path.with_suffix(".json")


class Recorder:
    def __init__(self, path: Path, target: str = "") -> None:
        if path.exists():
            raise SessionError(f"{path} already exists. Pick another name, or delete it first.")
        if not path.parent.is_dir():
            raise SessionError(f"the folder {path.parent} does not exist")
        self.path = path
        self.started_at = datetime.now().astimezone()
        self.target = target
        self.items: list[dict[str, Any]] = []
        self._t0 = time.monotonic()
        self.save()  # fail now, not at the end of a long session, if the file cannot be written

    def _add(self, kind: str, **data: Any) -> None:
        self.items.append({"t": round(time.monotonic() - self._t0, 3), "kind": kind, **data})

    def user(self, text: str) -> None:
        self._add("user", text=text)

    def event(self, event: BaseEvent) -> None:
        self._add("event", event=event.model_dump(mode="json", by_alias=True, exclude_none=True))

    def resume(self, entries: list[dict[str, Any]]) -> None:
        self._add("resume", entries=entries)

    def submit(self, text: str, props: dict[str, Any] | None) -> None:
        self._add("submit", text=text, props=props or {})

    def new_chat(self) -> None:
        self._add("new")

    def save(self) -> None:
        from gentui.cli import _version  # the installed version, for the file's header

        document = {
            "format": FORMAT, "version": VERSION, "gentui": _version(),
            "recorded_at": self.started_at.isoformat(timespec="seconds"), "target": self.target,
            "items": self.items,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(document, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)  # never leaves a half-written file behind
        except OSError as exc:
            raise SessionError(f"cannot write {self.path}: {exc}") from exc


@dataclass
class Item:
    t: float  # seconds since the recording started
    v: float  # the same moment on the replay timeline, where long waits are squeezed
    kind: str
    data: dict[str, Any]
    event: BaseEvent | None = None


@dataclass
class Session:
    path: Path
    recorded_at: datetime
    target: str
    items: list[Item]

    @property
    def duration(self) -> float:
        return self.items[-1].v if self.items else 0.0


def load(path: Path) -> Session:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SessionError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise SessionError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise SessionError(f"{path} is not a Gentui session file")
    if raw.get("version") != VERSION:
        raise SessionError(f"{path} is version {raw.get('version')!r}; this Gentui reads version {VERSION}")
    try:
        started = datetime.fromisoformat(raw["recorded_at"])
    except (KeyError, TypeError, ValueError):
        started = datetime.now().astimezone()
    items: list[Item] = []
    v = last_t = 0.0
    for n, entry in enumerate(raw.get("items") or [], 1):
        try:
            t, kind = float(entry["t"]), entry["kind"]
            if kind not in KINDS:
                raise ValueError(f"unknown kind {kind!r}")
            event = _event_adapter.validate_python(entry["event"]) if kind == "event" else None
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise SessionError(f"{path}: item {n} is not valid ({str(exc).splitlines()[0]})") from exc
        v += min(max(t - last_t, 0.0), IDLE_CAP) if items else 0.0
        last_t = t
        items.append(Item(t, v, kind, entry, event))
    return Session(path, started, str(raw.get("target") or ""), items)
