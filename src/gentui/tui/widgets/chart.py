"""Chart widget: renders the `show_chart` tool call as a terminal plot (plotext).

Spec (the tool's arguments):

    type      "line" | "bar" | "hbar" | "stacked_bar" | "area" | "scatter" | "histogram" | "box" | "heatmap" | "pie"
    title     heading
    x         x values or category labels (not used by "histogram" and "box")
    series    [{"name": str, "values": [numbers]}, ...]   one entry per line/bar group
    x_label, y_label   optional axis titles
    bins      histogram bins (default 10)

How each type reads `series`: line / area / scatter / bar / hbar: one entry per line or bar group, one value per `x`.
stacked_bar: one entry per layer of the stack. histogram: the first entry's values are binned. box: one entry per box
(its values are the sample). heatmap: one entry per row (its name labels the row), `x` names the columns. pie: the first
entry's values are the slices and `x` names them (drawn as percentage bars: a circle does not fit a terminal).
"""

import math
from numbers import Number
from typing import Any

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static
from textual_plotext import PlotextPlot

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

KINDS = ("line", "bar", "hbar", "stacked_bar", "area", "scatter", "histogram", "box", "heatmap", "pie")
MAX_TICKS = 10  # label this many x positions at most, so long date axes stay readable


_COLD, _HOT = (33, 40, 80), (242, 196, 109)  # heatmap colours: low values dark blue, high values gold


def _numbers(values: list[Any], what: str) -> list[float]:
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be numbers") from None


def _checked(spec: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """The chart type and series of `spec`. Raises ValueError for a bad spec."""
    kind = str(spec.get("type", "line")).lower()
    if kind not in KINDS:
        raise ValueError(f"unknown chart type {kind!r} (use {', '.join(KINDS)})")
    series = spec.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("series is empty")
    for s in series:
        if not isinstance(s, dict) or not isinstance(s.get("values"), list):
            raise ValueError("each series needs a name and a list of values")
    return kind, series


def _columns(spec: dict[str, Any], series: list[dict[str, Any]]) -> list[Any]:
    """The x values (or column / slice labels), one per value in every series."""
    x = list(spec.get("x") or range(1, len(series[0]["values"]) + 1))
    for s in series:
        if len(s["values"]) != len(x):
            raise ValueError(f"series {s.get('name', '?')!r} has {len(s['values'])} values for {len(x)} x points")
    return x


def _names(series: list[dict[str, Any]]) -> list[str]:
    return [str(s.get("name", f"series {i + 1}")) for i, s in enumerate(series)]


def draw_chart(plt: Any, spec: dict[str, Any]) -> None:
    """Draw `spec` on a plotext module/object. Raises ValueError for a bad spec. (A heatmap is a table: see `heatmap`.)"""
    kind, series = _checked(spec)
    if kind == "heatmap":
        raise ValueError("a heatmap is drawn as a table, not a plot")

    plt.clear_figure()
    plt.title(str(spec.get("title", "")))
    if spec.get("x_label"):
        plt.xlabel(str(spec["x_label"]))
    if spec.get("y_label"):
        plt.ylabel(str(spec["y_label"]))

    if kind == "histogram":
        plt.hist(_numbers(series[0]["values"], "values"), int(spec.get("bins") or 10))
        return

    names = _names(series)
    if kind == "box":
        samples = [_numbers(s["values"], "values") for s in series]
        if not all(samples):
            raise ValueError("each box needs at least one value")
        plt.box(names, samples)
        return

    x = _columns(spec, series)
    data = [_numbers(s["values"], "values") for s in series]
    labels = [str(v) for v in x]

    if kind == "pie":
        total = sum(data[0])
        if total <= 0 or any(v < 0 for v in data[0]):
            raise ValueError("pie values must be positive")
        shares = [100 * v / total for v in data[0]]
        plt.bar([f"{label} {share:.0f}%" for label, share in zip(labels, shares)], shares, orientation="horizontal")
        plt.xlabel("% of total")
        return

    if kind in ("bar", "hbar", "stacked_bar"):
        horizontal = {"orientation": "horizontal"} if kind == "hbar" else {}
        if kind == "stacked_bar":
            plt.stacked_bar(labels, data, labels=names)
        elif len(series) == 1:
            plt.bar(labels, data[0], label=names[0], **horizontal)
        else:
            plt.multiple_bar(labels, data, labels=names, **horizontal)
        return

    numeric_x = all(isinstance(v, Number) and not isinstance(v, bool) for v in x)
    xs = x if numeric_x else list(range(len(x)))
    for name, ys in zip(names, data):
        if kind == "scatter":
            plt.scatter(xs, ys, label=name)
        else:
            plt.plot(xs, ys, label=name, fillx=(kind == "area"))
    if kind == "area" and min(min(ys) for ys in data) >= 0:
        plt.ylim(0, max(max(ys) for ys in data))  # fill down to zero, not to the lowest value
    if not numeric_x:
        step = max(1, math.ceil(len(x) / MAX_TICKS))
        plt.xticks(xs[::step], labels[::step])


def heatmap(spec: dict[str, Any]) -> Table:
    """A heatmap as a table: one row per series, one column per `x`, cells shaded by value. Raises ValueError."""
    kind, series = _checked(spec)
    columns = [str(v) for v in _columns(spec, series)]
    rows = [_numbers(s["values"], "values") for s in series]
    flat = [v for row in rows for v in row]
    lo, hi = min(flat), max(flat)
    table = Table(title=str(spec.get("title", "")) or None, box=None, pad_edge=False, show_edge=False)
    table.add_column(str(spec.get("y_label", "")), style="bold")
    for column in columns:
        table.add_column(column, justify="right")
    for name, row in zip(_names(series), rows):
        cells = []
        for v in row:
            t = (v - lo) / ((hi - lo) or 1)
            red, green, blue = (int(a + (b - a) * t) for a, b in zip(_COLD, _HOT))
            ink = "black" if 0.299 * red + 0.587 * green + 0.114 * blue > 140 else "white"
            cells.append(Text(f" {v:g} ", style=f"{ink} on rgb({red},{green},{blue})"))
        table.add_row(name, *cells)
    return table


@register_widget("show_chart")
class ChartWidget(ToolWidget):
    DEFAULT_CSS = """
    ChartWidget { border: none; border-left: thick $success 60%; }
    ChartWidget PlotextPlot { height: 18; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="body")
        yield PlotextPlot(id="plot")

    def on_mount(self) -> None:
        self.query_one(PlotextPlot).display = False

    def on_start(self) -> None:
        self.show(Text("▤ Drawing a chart…", style="dim italic"))  # skeleton

    def on_end(self, args: dict[str, Any]) -> None:
        super().on_end(args)
        plot = self.query_one(PlotextPlot)
        try:
            if str(args.get("type", "")).lower() == "heatmap":
                plot.display = False
                self.show(heatmap(args))
                return
            draw_chart(plot.plt, args)
        except (ValueError, TypeError) as exc:
            plot.display = False
            self.show(Text(f"▤ Could not draw chart: {exc}", style="red"))
            return
        self.show(Text(""))
        self.query_one("#body").display = False
        plot.display = True
        plot.refresh(layout=True)
