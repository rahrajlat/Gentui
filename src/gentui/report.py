"""Export a comparison as one self-contained HTML page: `e` in the compare view, or `--compare a,b --export FILE`.

The page holds everything the compare view shows: for each prompt the judge's panel (score and comment), then both
sides' answers, tool calls, tables, command output and every chart, drawn as inline SVG so they need nothing to view.
Changed blocks are marked, and changed text is shown word by word. It has no scripts and loads nothing from the web.
"""

import asyncio
import html
import json
import math
import re
from collections.abc import Iterable
from datetime import datetime
from difflib import SequenceMatcher
from numbers import Number
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from gentui.judge import Verdict
from gentui.session import Session
from gentui.tui.compare import Block, Pair, align, blocks_of, verdict_for

KINDS = ("line", "bar", "scatter", "histogram")
PALETTE = ["#4FD6C8", "#A78BFA", "#F2C46D", "#F27C86", "#7DD3FC", "#7BD88F"]
_md = MarkdownIt("commonmark", {"html": False}).enable("table")  # raw HTML in an answer is escaped, not passed on


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


# -- charts, as SVG ---------------------------------------------------------------------------------


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Round tick values (1, 2, 2.5, 5 x 10^k) covering lo..hi."""
    span = (hi - lo) or 1.0
    raw = span / n
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    first = math.floor(lo / step) * step
    ticks = [first]
    while ticks[-1] < hi - 1e-9:
        ticks.append(ticks[-1] + step)
    return ticks


def _fmt(v: float) -> str:
    return f"{v:.0f}" if abs(v) >= 100 or v == int(v) else f"{v:.2f}".rstrip("0").rstrip(".")


def _numbers(values: list[Any]) -> list[float]:
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError("values must be numbers") from None


def chart_svg(spec: dict[str, Any]) -> str:
    """The `show_chart` arguments as an inline SVG (bar, line, scatter or histogram). Raises ValueError if unusable."""
    kind = str(spec.get("type", "line")).lower()
    if kind not in KINDS:
        raise ValueError(f"unknown chart type {kind!r}")
    series = spec.get("series")
    if not isinstance(series, list) or not series or not all(isinstance(s, dict) and isinstance(s.get("values"), list) for s in series):
        raise ValueError("series is empty or malformed")
    names = [str(s.get("name", f"series {i + 1}")) for i, s in enumerate(series)]
    data = [_numbers(s["values"]) for s in series]

    if kind == "histogram":
        values, bins = data[0], max(int(spec.get("bins") or 10), 1)
        lo, hi = min(values), max(values)
        width = (hi - lo) / bins or 1.0
        counts = [0] * bins
        for v in values:
            counts[min(int((v - lo) / width), bins - 1)] += 1
        labels = [f"{lo + i * width:.3g}" for i in range(bins)]
        x, data, names, kind = labels, [[float(c) for c in counts]], ["count"], "bar"
    else:
        x = list(spec.get("x") or range(1, len(data[0]) + 1))
        for name, ys in zip(names, data):
            if len(ys) != len(x):
                raise ValueError(f"series {name!r} has {len(ys)} values for {len(x)} x points")

    W, H, L, R, T, B = 640, 350, 56, 16, 48, 56
    pw, ph = W - L - R, H - T - B
    flat = [v for ys in data for v in ys]
    lo, hi = min(0.0, min(flat)), max(flat)
    ticks = _ticks(lo, hi)
    lo, hi = ticks[0], ticks[-1]
    y = lambda v: T + ph - (v - lo) / (hi - lo) * ph  # noqa: E731
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(spec.get("title", "chart"))}">']
    out.append(f'<text x="{W / 2}" y="20" class="ctitle" text-anchor="middle">{esc(spec.get("title", ""))}</text>')
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="grid"/>')
        out.append(f'<text x="{L - 6}" y="{y(t) + 4:.1f}" class="tick" text-anchor="end">{_fmt(t)}</text>')
    out.append(f'<line x1="{L}" x2="{L}" y1="{T}" y2="{T + ph}" class="axis"/><line x1="{L}" x2="{W - R}" y1="{y(0 if lo <= 0 else lo):.1f}" y2="{y(0 if lo <= 0 else lo):.1f}" class="axis"/>')

    numeric_x = kind in ("line", "scatter") and all(isinstance(v, Number) and not isinstance(v, bool) for v in x)
    if numeric_x:
        xlo, xhi = min(x), max(x)
        px = lambda i: L + (x[i] - xlo) / ((xhi - xlo) or 1) * pw  # noqa: E731
    else:
        slot = pw / len(x)
        px = lambda i: L + slot * (i + 0.5)  # noqa: E731
    base = y(0 if lo <= 0 else lo)

    if kind == "bar":
        group = slot * 0.8 / len(data)
        for s, ys in enumerate(data):
            for i, v in enumerate(ys):
                bx = L + slot * i + slot * 0.1 + group * s
                top = y(v)
                out.append(f'<rect x="{bx:.1f}" y="{min(top, base):.1f}" width="{group - 1:.1f}" height="{abs(base - top):.1f}" fill="{PALETTE[s % 6]}"><title>{esc(names[s])}, {esc(x[i])}: {_fmt(v)}</title></rect>')
    else:
        for s, ys in enumerate(data):
            colour = PALETTE[s % 6]
            if kind == "line":
                points = " ".join(f"{px(i):.1f},{y(v):.1f}" for i, v in enumerate(ys))
                out.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="2"/>')
            for i, v in enumerate(ys):
                out.append(f'<circle cx="{px(i):.1f}" cy="{y(v):.1f}" r="{4 if kind == "scatter" else 3}" fill="{colour}"><title>{esc(names[s])}, {esc(x[i])}: {_fmt(v)}</title></circle>')

    step = max(1, len(x) // 10)
    for i in range(0, len(x), step):
        label = str(x[i])
        label = label if len(label) <= 14 else label[:13] + "…"
        out.append(f'<text x="{px(i):.1f}" y="{T + ph + 16}" class="tick" text-anchor="middle">{esc(label)}</text>')
    if spec.get("x_label"):
        out.append(f'<text x="{L + pw / 2}" y="{H - 8}" class="tick" text-anchor="middle">{esc(spec["x_label"])}</text>')
    if spec.get("y_label"):
        out.append(f'<text x="12" y="{T + ph / 2}" class="tick" text-anchor="middle" transform="rotate(-90 12 {T + ph / 2})">{esc(spec["y_label"])}</text>')
    if len(data) > 1 or spec.get("type") != "histogram":
        for s, name in enumerate(names):
            out.append(f'<rect x="{L + 8 + s * 120}" y="{T - 16}" width="10" height="10" fill="{PALETTE[s % 6]}"/>'
                       f'<text x="{L + 22 + s * 120}" y="{T - 7}" class="tick">{esc(name)}</text>')
    out.append("</svg>")
    return "".join(out)


# -- one block -------------------------------------------------------------------------------------


def words(old: str, new: str, side: int) -> str:
    """The text of one side with the words that differ marked: <del> on the left, <ins> on the right."""
    tokens = lambda s: re.findall(r"\s+|\S+", s)  # noqa: E731
    a, b = tokens(old), tokens(new)
    out = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        mine, tag = (a[i1:i2], "del") if side == 0 else (b[j1:j2], "ins")
        text = esc("".join(mine))
        out.append(text if op == "equal" or not text else f"<{tag}>{text}</{tag}>")
    return "".join(out)


def _json(value: Any) -> str:
    try:
        return json.dumps(json.loads(value) if isinstance(value, str) else value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def tool_html(block: Block) -> str:
    try:
        args = json.loads(block.args) if block.args.strip() else {}
        args = args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        args = {}
    result = block.result or ""
    name = block.name
    head = f'<div class="tool-name">{esc(name)}</div>'
    try:
        if name == "show_chart":
            return f'<div class="tool">{head}{chart_svg(args)}</div>'
        if name == "show_table":
            cols, rows = args.get("columns") or [], args.get("rows") or []
            table = "".join(f"<th>{esc(c)}</th>" for c in cols)
            body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows[:200])
            return f'<div class="tool">{head}<b>{esc(args.get("title", "Table"))}</b><table><thead><tr>{table}</tr></thead><tbody>{body}</tbody></table></div>'
    except (ValueError, TypeError) as exc:
        return f'<div class="tool">{head}<p class="err">Could not draw this {esc(name)}: {esc(exc)}</p><pre>{esc(_json(args))}</pre></div>'
    if name == "propose_command":
        risk = esc(args.get("risk", "caution"))
        return (f'<div class="tool">{head}<span class="badge {risk}">{risk}</span><pre>{esc(args.get("command", ""))}</pre>'
                f'<p>{esc(args.get("explanation", ""))}</p></div>')
    if name == "run_command":
        try:
            data = json.loads(result)
            return (f'<div class="tool">{head}<pre class="cmd">$ {esc(data.get("command", ""))}   '
                    f'<span class="badge {"good" if data.get("exit_code") == 0 else "bad"}">exit {esc(data.get("exit_code"))}</span></pre>'
                    f'<pre>{esc(data.get("output", ""))}</pre></div>')
        except (ValueError, AttributeError):
            pass
    if name == "todo_write" and isinstance(args.get("todos"), list):
        items = "".join(f'<li class="{esc(t.get("status", ""))}">{esc(t.get("content", ""))}</li>' for t in args["todos"] if isinstance(t, dict))
        return f'<div class="tool">{head}<ul class="plan">{items}</ul></div>'
    shown = f"<pre>{esc(_json(args))}</pre>" if args else ""
    answer = f"<details><summary>result</summary><pre>{esc(_json(result))}</pre></details>" if result else ""
    return f'<div class="tool">{head}{shown}{answer}</div>'


def block_html(block: Block, other: Block | None, side: int, status: str) -> str:
    if block.kind == "reasoning":
        return f'<details class="thought"><summary>◈ Thought</summary><pre>{esc(block.text.strip())}</pre></details>'
    if block.kind == "tool":
        return tool_html(block)
    rendered = _md.render(block.text) if block.kind == "text" else f"<p>{esc(block.text)}</p>"
    mark = "❯" if block.kind == "user" else "◈"
    if status == "changed" and other is not None:
        old, new = (block.text, other.text) if side == 0 else (other.text, block.text)
        return (f'<div class="{block.kind}"><span class="mark">{mark}</span><div class="words">{words(old, new, side)}</div></div>'
                f'<details class="rendered"><summary>rendered</summary>{rendered}</details>')
    return f'<div class="{block.kind}"><span class="mark">{mark}</span><div>{rendered}</div></div>'


# -- the page --------------------------------------------------------------------------------------


def verdict_html(verdict: Verdict | None, judge: str) -> str:
    if verdict is None:
        return ""
    title = f"⚖ Judge · {esc(judge)}"
    if verdict.failed:
        return f'<section class="judge failed"><h3>{title}</h3><p>Judge failed: {esc(verdict.reason)}</p></section>'
    score = verdict.score or 0.0
    level = "good" if score >= 0.8 else "ok" if score >= 0.5 else "bad"
    return (f'<section class="judge {level}"><h3>{title}</h3><div class="score"><b>{score:.0%} match</b>'
            f'<span class="bar"><i style="width:{score * 100:.0f}%"></i></span></div><p>{esc(verdict.reason)}</p></section>')


def turns_of(pairs: list[Pair]) -> list[tuple[int, list[Pair]]]:
    """Pairs grouped by prompt (1, 2, ...), as the compare view numbers them. Anything before the first prompt is turn 0."""
    turns: list[tuple[int, list[Pair]]] = []
    for pair in pairs:
        if any(b is not None and b.kind == "user" for b in (pair.left, pair.right)):
            turns.append((len(turns) + 1 if turns[-1:] and turns[-1][0] else 1, []))
        elif not turns:
            turns.append((0, []))
        turns[-1][1].append(pair)
    return turns


def render(left: str, right: str, pairs: list[Pair], verdicts: dict[int, Verdict], judge: str | None) -> str:
    """The whole report. `verdicts` is keyed by prompt number (1, 2, ...)."""
    count = lambda status: sum(p.status == status for p in pairs)  # noqa: E731
    scores = [v.score for v in verdicts.values() if v.score is not None]
    average = f' · judge average <b>{sum(scores) / len(scores):.0%}</b>' if scores else ""
    sections = []
    for number, group in turns_of(pairs):
        rows = []
        for pair in group:
            cells = []
            for side, (block, other) in enumerate(((pair.left, pair.right), (pair.right, pair.left))):
                css = "empty" if block is None else pair.status
                cells.append(f'<div class="cell {css}">{block_html(block, other, side, pair.status) if block else ""}</div>')
            rows.append(f'<div class="pair">{"".join(cells)}</div>')
        judged = verdict_html(verdicts.get(number), judge or "") if number else ""
        label = f"Prompt {number}" if number else "Before the first prompt"
        sections.append(f'<section class="turn"><h2>{label}</h2>{judged}{"".join(rows)}</section>')
    return PAGE.format(
        title=esc(f"{left} vs {right}"), left=esc(left), right=esc(right), when=datetime.now().strftime("%Y-%m-%d %H:%M"),
        summary=f'{count("same")} same · {count("changed")} changed · {count("removed")} only in {esc(left)} · {count("added")} only in {esc(right)}{average}',
        sections="".join(sections),
    )


async def build(left: Session, right: Session, judge: str | None = None, show_reasoning: bool = True) -> str:
    """Compare two sessions and return the report, judging every prompt first when `judge` is a judge name."""
    pairs = align(blocks_of(left, show_reasoning)[0], blocks_of(right, show_reasoning)[0])
    turns = [(n, group) for n, group in turns_of(pairs) if n]
    verdicts: dict[int, Verdict] = {}
    if judge:
        gate = asyncio.Semaphore(3)

        async def one(n: int, group: list[Pair]) -> None:
            async with gate:
                verdicts[n] = await verdict_for(judge, group)

        await asyncio.gather(*(one(n, group) for n, group in turns))
    return render(left.path.stem, right.path.stem, pairs, verdicts, judge)


def save(path: Path, content: str, overwrite: bool = False) -> Path:
    """Write the report. An existing file is never overwritten: a free `-1`, `-2`... name is used, unless `overwrite`."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate, n = path, 0
    while candidate.exists() and not overwrite:
        n += 1
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
    candidate.write_text(content, encoding="utf-8")
    return candidate


def default_name(left: str, right: str) -> Path:
    clean = lambda s: re.sub(r"[^A-Za-z0-9._-]+", "_", s)  # noqa: E731
    return Path(f"compare-{clean(left)}-vs-{clean(right)}.html")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f7f9; --fg:#1b1f27; --muted:#667085; --card:#fff; --line:#d9dde4; --code:#eef0f4;
  --good:#1f8f4e; --ok:#b7791f; --bad:#c53030; --add:#e6f6ec; --del:#fdecec; --chg:#fff6dd; --accent:#0f8f84; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14161b; --fg:#e6e9ef; --muted:#8b93a1; --card:#1d2027; --line:#2e323c;
  --code:#242832; --good:#7bd88f; --ok:#f2c46d; --bad:#f27c86; --add:#16301f; --del:#3a1d20; --chg:#352d14; --accent:#4fd6c8; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:1500px; margin:0 auto; padding:24px 16px 64px; }}
h1 {{ margin:0 0 4px; font-size:22px; }} h2 {{ font-size:17px; margin:0 0 8px; }} h3 {{ margin:0 0 6px; font-size:14px; }}
.meta {{ color:var(--muted); font-size:13px; }} .summary {{ margin:12px 0; }}
.legend span {{ display:inline-block; padding:1px 8px; margin-right:6px; border-radius:4px; font-size:12px; border-left:4px solid; }}
.heads, .pair {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.heads {{ position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:2; font-weight:600; }}
.turn {{ margin-top:28px; }}
.cell {{ min-width:0; margin-bottom:10px; padding:2px 10px; border-left:4px solid transparent; border-radius:4px; overflow-wrap:anywhere; }}
.cell.removed {{ background:var(--del); border-color:var(--bad); }} .cell.added {{ background:var(--add); border-color:var(--good); }}
.cell.changed {{ background:var(--chg); border-color:var(--ok); }} .cell.empty {{ visibility:hidden; }}
.user, .text {{ display:flex; gap:8px; }} .user {{ background:var(--code); padding:2px 8px; border-radius:4px; font-weight:600; }}
.mark {{ color:var(--accent); font-weight:700; }} .words {{ white-space:pre-wrap; flex:1; }}
del {{ background:var(--del); color:var(--bad); text-decoration:none; font-weight:600; }}
ins {{ background:var(--add); color:var(--good); text-decoration:none; font-weight:600; }}
.tool {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:8px 10px; margin:6px 0; }}
.tool-name {{ color:var(--muted); font:600 12px ui-monospace,monospace; margin-bottom:4px; }}
pre {{ margin:6px 0; padding:8px; background:var(--code); border-radius:4px; overflow-x:auto; white-space:pre-wrap; font:13px ui-monospace,monospace; }}
table {{ border-collapse:collapse; margin:6px 0; font-size:13px; }} th, td {{ border:1px solid var(--line); padding:3px 8px; text-align:left; }}
th {{ background:var(--code); }}
.badge {{ font:700 11px ui-monospace,monospace; padding:1px 6px; border-radius:4px; background:var(--code); text-transform:uppercase; }}
.badge.safe, .badge.good {{ color:var(--good); }} .badge.caution {{ color:var(--ok); }} .badge.dangerous, .badge.bad {{ color:var(--bad); }}
.err {{ color:var(--bad); }} .plan {{ list-style:none; padding:0; margin:4px 0; }} .plan li::before {{ content:"☐ "; }}
.plan li.completed::before {{ content:"✔ "; color:var(--good); }} .plan li.in_progress::before {{ content:"◐ "; color:var(--ok); }}
details {{ margin:6px 0; }} summary {{ cursor:pointer; color:var(--muted); font-size:13px; }}
.judge {{ border:2px solid var(--line); border-radius:8px; padding:10px 14px; margin:0 0 12px; background:var(--card); }}
.judge.good {{ border-color:var(--good); }} .judge.ok {{ border-color:var(--ok); }} .judge.bad, .judge.failed {{ border-color:var(--bad); }}
.judge p {{ margin:6px 0 0; }} .score {{ display:flex; align-items:center; gap:12px; }} .score b {{ font-size:18px; }}
.judge.good b {{ color:var(--good); }} .judge.ok b {{ color:var(--ok); }} .judge.bad b {{ color:var(--bad); }}
.bar {{ flex:0 0 220px; height:10px; background:var(--code); border-radius:5px; overflow:hidden; }}
.bar i {{ display:block; height:100%; background:currentColor; }} .judge.good .bar {{ color:var(--good); }}
.judge.ok .bar {{ color:var(--ok); }} .judge.bad .bar {{ color:var(--bad); }}
svg.chart {{ width:100%; max-width:640px; height:auto; }} svg .grid {{ stroke:var(--line); }} svg .axis {{ stroke:var(--muted); }}
svg .tick {{ fill:var(--muted); font:11px system-ui,sans-serif; }} svg .ctitle {{ fill:var(--fg); font:600 13px system-ui,sans-serif; }}
@media (max-width:800px) {{ .heads, .pair {{ grid-template-columns:1fr; }} }}
@media print {{ .heads {{ position:static; }} body {{ background:#fff; }} }}
</style></head><body><main>
<h1>Gentui comparison: {left} vs {right}</h1>
<div class="meta">exported {when}</div>
<div class="summary">{summary}</div>
<div class="legend"><span style="background:var(--add);border-color:var(--good)">only on the right</span><span style="background:var(--del);border-color:var(--bad)">only on the left</span><span style="background:var(--chg);border-color:var(--ok)">changed</span></div>
<div class="heads"><div>{left}</div><div>{right}</div></div>
{sections}
</main></body></html>
"""
