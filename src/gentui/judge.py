"""Judges for `gentui --compare`: something that reads two answers to the same prompt and says how well they match.

A judge is a function registered with `@register_judge("name")`. It gets a `Case` (the prompt, both sides' answers
and tool calls) and returns a score from 0 to 1 and a short comment:

    from gentui.plugins import register_judge

    @register_judge("mine")
    async def mine(case):
        return {"score": 0.9, "reason": "same facts, B is shorter"}

Load it with `--plugin my_judge.py`; it then appears in the Judge drop-down of the compare view. Gentui ships one judge,
`ollama:<model>`, which asks a model on Ollama (Ollama Cloud by default). Verdicts are cached on disk, so judging the same
pair of answers again is free.

What a judge is sent is whatever the agent said, including tool output: that can hold secrets, and it leaves your machine
when the judge is a hosted model.
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from gentui import plugins

MAX_CHARS = 6000  # per answer or tool result sent to the model; the rest is cut


@dataclass
class Case:
    """One prompt, as answered on the left and on the right."""

    prompt: str
    left: str  # everything the agent said, as text
    right: str
    left_tools: list[dict[str, Any]] = field(default_factory=list)  # {"name", "args", "result"}
    right_tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Verdict:
    score: float | None  # 0 (nothing alike) .. 1 (same); None when the judge failed
    reason: str
    cached: bool = False

    @property
    def failed(self) -> bool:
        return self.score is None


def as_verdict(value: Any) -> Verdict:
    """Accept a Verdict, a {"score", "reason"} mapping or a (score, reason) tuple from a judge."""
    if isinstance(value, Verdict):
        return value
    if isinstance(value, dict):
        score, reason = value.get("score"), value.get("reason") or value.get("comment") or ""
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        score, reason = value
    else:
        raise ValueError(f"a judge must return {{'score': 0..1, 'reason': '...'}}, got {value!r}")
    try:
        score = min(max(float(score), 0.0), 1.0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"the judge's score {score!r} is not a number") from exc
    return Verdict(score, str(reason).strip())


# -- cache ------------------------------------------------------------------------------------------


def cache_path() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "gentui" / "judge.json"


def _key(judge_name: str, case: Case) -> str:
    return hashlib.sha256(json.dumps([judge_name, asdict(case)], sort_keys=True).encode()).hexdigest()


def _read_cache() -> dict[str, Any]:
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(cache: dict[str, Any]) -> None:
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # a cache that cannot be written only costs a repeat call


async def judge_case(name: str, case: Case) -> Verdict:
    """Ask judge `name` about `case`. Never raises: a failure comes back as a Verdict with no score."""
    fn = plugins.JUDGES.get(name)
    if fn is None:
        return Verdict(None, f"no judge called {name!r}")
    key = _key(name, case)
    cache = _read_cache()
    if key in cache:
        try:
            return Verdict(float(cache[key]["score"]), str(cache[key]["reason"]), cached=True)
        except (KeyError, TypeError, ValueError):
            pass
    try:
        verdict = as_verdict(await plugins.call(fn, case))
    except Exception as exc:  # noqa: BLE001 - one bad verdict must not stop the comparison
        return Verdict(None, f"{type(exc).__name__}: {exc}"[:300])
    cache = _read_cache()  # another judge may have written meanwhile
    cache[key] = {"score": verdict.score, "reason": verdict.reason}
    _write_cache(cache)
    return verdict


# -- the built-in judge: a model on Ollama -------------------------------------------------------------

OLLAMA_MODEL = os.environ.get("GENTUI_JUDGE_MODEL") or os.environ.get("OLLAMA_MODEL") or "gpt-oss:120b"
LOCAL_OLLAMA = "http://localhost:11434"


def ollama_host(model: str) -> str:
    """OLLAMA_HOST if set. Otherwise a ":cloud" / "-cloud" model (e.g. gpt-oss:120b-cloud) goes through the local
    Ollama, which forwards it to Ollama Cloud once you have run `ollama signin` (no API key); any other model
    goes straight to ollama.com, which needs OLLAMA_API_KEY."""
    host = os.environ.get("OLLAMA_HOST", "").rstrip("/")
    if not host:
        return LOCAL_OLLAMA if model.endswith("cloud") else "https://ollama.com"
    return host if "://" in host else "http://" + host  # the Ollama CLI writes OLLAMA_HOST=localhost:11434


RUBRIC = """You compare two answers (A and B) that two versions of an AI agent gave to the same user prompt.
Judge whether they MATCH in substance: the same facts and numbers, the same conclusion, the same actions taken
(tool calls), nothing important added, missing or contradicted. Ignore wording, order, length and formatting.

Score from 0 to 1: 1 = same in substance; 0.7-0.9 = same conclusion, minor details differ; 0.4-0.6 = partly
different (a fact, step or tool result differs); 0-0.3 = different or contradicting.
Answer with JSON only: {"score": <0..1>, "reason": "<one or two short sentences naming the key difference>"}"""

SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "number"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
}


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + f"\n[... {len(text) - MAX_CHARS} more characters]"


def _tools(calls: list[dict[str, Any]]) -> str:
    if not calls:
        return "(no tool calls)"
    return "\n".join(
        f"- {c['name']}({_clip(str(c.get('args') or ''))}) -> {_clip(str(c.get('result') or '(no result)'))}" for c in calls
    )


def ollama_prompt(case: Case) -> str:
    return (
        f"User prompt:\n{_clip(case.prompt)}\n\n"
        f"--- Answer A ---\n{_clip(case.left) or '(empty)'}\n\nTool calls in A:\n{_tools(case.left_tools)}\n\n"
        f"--- Answer B ---\n{_clip(case.right) or '(empty)'}\n\nTool calls in B:\n{_tools(case.right_tools)}"
    )


def ollama_judge_for(model: str):
    """A judge that asks `model` on Ollama (see `ollama_host` for where the request goes)."""

    async def ollama_judge(case: Case) -> Verdict:
        host = ollama_host(model)
        headers = {}
        if key := os.environ.get("OLLAMA_API_KEY"):
            headers["Authorization"] = f"Bearer {key}"
        elif "ollama.com" in host:
            raise RuntimeError(
                "set OLLAMA_API_KEY (ollama.com/settings/keys), or use a '-cloud' model through a signed-in local "
                "Ollama (`ollama signin`)"
            )
        body = {
            "model": model,
            "stream": False,
            "format": SCHEMA,
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": RUBRIC}, {"role": "user", "content": ollama_prompt(case)}],
        }
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f"{host}/api/chat", json=body, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Ollama answered {response.status_code}: {response.text[:200]}")
        content = response.json().get("message", {}).get("content", "")
        try:
            return as_verdict(json.loads(content))
        except ValueError as exc:
            raise RuntimeError(f"the model did not return the JSON asked for: {content[:200]!r}") from exc

    return ollama_judge


def register_ollama(model: str) -> str:
    """Make `ollama:<model>` available as a judge and return its name."""
    name = f"ollama:{model}"
    if name not in plugins.JUDGES:
        plugins.register_judge(name)(ollama_judge_for(model))
    return name


register_ollama(OLLAMA_MODEL)


def resolve(want: str) -> str | None:
    """The registered judge a `--judge` value means: an exact name, `ollama` for the first `ollama:<model>`, or
    `ollama:<any model>` (registered on the spot). None if there is no such judge."""
    if want.startswith("ollama:") and want not in plugins.JUDGES:
        return register_ollama(want.removeprefix("ollama:"))
    return next((n for n in plugins.JUDGES if n == want or n.startswith(want + ":")), None)
