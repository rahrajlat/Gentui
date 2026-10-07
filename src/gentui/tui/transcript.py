"""A record of the conversation, for `/export_md`.

The UI is made of widgets, not text, so the app feeds this recorder as events arrive: your messages, the agent's
replies, its reasoning, tool calls and results, your approve / reject decisions, and errors.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def fence(text: str, lang: str = "") -> str:
    """A fenced code block that cannot be broken by backticks inside `text`."""
    ticks = "```"
    while ticks in text:
        ticks += "`"
    return f"{ticks}{lang}\n{text.rstrip()}\n{ticks}"


def _table(args: dict[str, Any]) -> str | None:
    """A `show_table` call as a Markdown table, or None if the arguments are not a usable table."""
    columns, rows = args.get("columns"), args.get("rows")
    if not isinstance(columns, list) or not columns or not isinstance(rows, list):
        return None

    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(cell(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        if not isinstance(row, list):
            return None
        padded = (list(row) + [""] * len(columns))[: len(columns)]
        lines.append("| " + " | ".join(cell(v) for v in padded) + " |")
    return "\n".join(lines)


@dataclass
class Transcript:
    entries: list[dict[str, Any]] = field(default_factory=list)
    _open_text: dict[str, dict[str, Any]] = field(default_factory=dict)
    _tools: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def clear(self) -> None:
        self.entries.clear()
        self._open_text.clear()
        self._tools.clear()

    def _add(self, kind: str, **data: Any) -> dict[str, Any]:
        entry = {"kind": kind, "time": datetime.now(), **data}
        self.entries.append(entry)
        return entry

    # -- recording ---------------------------------------------------------------------------

    def user(self, text: str) -> None:
        self._add("user", text=text)

    def open_text(self, message_id: str) -> None:
        self._open_text[message_id] = self._add("assistant", text="")

    def append_text(self, message_id: str, delta: str) -> None:
        entry = self._open_text.get(message_id)
        if entry is None:  # content without a start event: still keep it
            entry = self._open_text[message_id] = self._add("assistant", text="")
        entry["text"] += delta

    def reasoning(self, text: str, seconds: int) -> None:
        if text.strip():
            self._add("reasoning", text=text, seconds=seconds)

    def tool_start(self, call_id: str, name: str) -> None:
        self._tools[call_id] = self._add("tool", name=name, args="", result=None)

    def tool_args(self, call_id: str, delta: str) -> None:
        if call_id in self._tools:
            self._tools[call_id]["args"] += delta

    def tool_result(self, call_id: str, content: str) -> None:
        if call_id in self._tools:
            self._tools[call_id]["result"] = content

    def decision(self, text: str) -> None:
        self._add("decision", text=text)

    def error(self, message: str) -> None:
        self._add("error", text=message)

    # -- export ------------------------------------------------------------------------------

    def to_markdown(self, *, backend: str = "", thread_id: str = "", time_format: str = "%H:%M",
                    now: datetime | None = None) -> str:
        now = now or datetime.now()
        out = [
            "# Gentui conversation",
            "",
            "| | |",
            "|---|---|",
            f"| Exported | {now:%Y-%m-%d %H:%M} |",
        ]
        if backend:
            out.append(f"| Backend | `{backend}` |")
        if thread_id:
            out.append(f"| Thread | `{thread_id}` |")
        out += ["", "---", ""]

        for e in self.entries:
            stamp = e["time"].strftime(time_format)
            kind = e["kind"]
            if kind == "user":
                out += [f"## You · {stamp}", "", e["text"].strip(), ""]
            elif kind == "assistant":
                if e["text"].strip():
                    out += [f"## Assistant · {stamp}", "", e["text"].strip(), ""]
            elif kind == "reasoning":
                out += [
                    "<details>",
                    f"<summary>◈ Thought for {e['seconds']}s</summary>",
                    "",
                    e["text"].strip(),
                    "",
                    "</details>",
                    "",
                ]
            elif kind == "tool":
                out += self._tool_markdown(e)
            elif kind == "decision":
                out += [f"> **{e['text']}** · {stamp}", ""]
            elif kind == "error":
                out += [f"> **Error:** {e['text']} · {stamp}", ""]
        return "\n".join(out).rstrip() + "\n"

    @staticmethod
    def _tool_markdown(e: dict[str, Any]) -> list[str]:
        raw = e["args"].strip()
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = None
        lines = [f"**Tool call:** `{e['name']}`", ""]
        table = _table(args) if e["name"] == "show_table" and isinstance(args, dict) else None
        if table:
            title = args.get("title")
            lines += ([f"*{title}*", ""] if title else []) + [table, ""]
        elif args is None:
            lines += [fence(raw), ""]
        elif args:
            lines += [fence(json.dumps(args, indent=2, ensure_ascii=False), "json"), ""]
        if e["result"] and not table:
            lines += ["**Result:**", "", fence(e["result"]), ""]
        return lines

    def save(self, path: Path, **meta: Any) -> Path:
        """Write the Markdown to `path`, never overwriting a file that already exists (adds -1, -2, ...)."""
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        candidate, n = path, 0
        while candidate.exists():
            n += 1
            candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        candidate.write_text(self.to_markdown(**meta), encoding="utf-8")
        return candidate
