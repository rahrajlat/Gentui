"""Loading a prompts file for `--prompts`: the messages Gentui sends for you, one after the other.

    prompts:
      - What are the 5 largest files here?
      - text: Now plot them as a bar chart

A bare list works too. Each item is a string, or a mapping with a `text` key.
"""

from pathlib import Path
from typing import Any

import yaml


class PromptsError(Exception):
    """A prompts file that cannot be read. The message is safe to show the user."""


def load(path: Path) -> list[str]:
    try:
        raw = yaml.safe_load(path.expanduser().read_text(encoding="utf-8"))
    except OSError as exc:
        raise PromptsError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except yaml.YAMLError as exc:
        raise PromptsError(f"{path} is not valid YAML: {exc}") from exc
    items: Any = raw.get("prompts") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise PromptsError(f"{path} needs a 'prompts:' list (or to be a list of prompts)")
    prompts = []
    for n, item in enumerate(items, 1):
        text = item.get("text") if isinstance(item, dict) else item
        if not isinstance(text, str) or not text.strip():
            raise PromptsError(f"{path}: prompt {n} must be text (a string, or a mapping with a 'text' key)")
        prompts.append(text.strip())
    if not prompts:
        raise PromptsError(f"{path} has no prompts")
    return prompts
