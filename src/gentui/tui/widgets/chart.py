"""Chart widget: renders the `show_chart` tool call as a terminal plot (plotext).

Spec (the tool's arguments):

    type      "line" | "bar" | "scatter" | "histogram"
    title     heading
    x         x values or category labels (not used by "histogram")
    series    [{"name": str, "values": [numbers]}, ...]   one entry per line/bar group
    x_label, y_label   optional axis titles
    bins      histogram bins (default 10)
"""

from numbers import Number
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static
from textual_plotext import PlotextPlot

from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

KINDS = ("line", "bar", "scatter", "histogram")


def _numbers(values: list[Any], what: str) -> list[float]:
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be numbers") from None


def draw_chart(plt: Any, spec: dict[str, Any]) -> None:
    """Draw `spec` on a plotext module/object. Raises ValueError for a bad spec."""
    kind = str(spec.get("type", "line")).lower()
    if kind not in KINDS:
        raise ValueError(f"unknown chart type {kind!r} (use {', '.join(KINDS)})")
    series = spec.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("series is empty")
    for s in series:
        if not isinstance(s, dict) or not isinstance(s.get("values"), list):
            raise ValueError("each series needs a name and a list of values")

    plt.clear_figure()
    plt.title(str(spec.get("title", "")))
    if spec.get("x_label"):
        plt.xlabel(str(spec["x_label"]))
    if spec.get("y_label"):
        plt.ylabel(str(spec["y_label"]))

    if kind == "histogram":
        plt.hist(_numbers(series[0]["values"], "values"), int(spec.get("bins") or 10))
        return

    x = list(spec.get("x") or range(1, len(series[0]["values"]) + 1))
    for s in series:
        if len(s["values"]) != len(x):
            raise ValueError(f"series {s.get('name', '?')!r} has {len(s['values'])} values for {len(x)} x points")
    names = [str(s.get("name", f"series {i + 1}")) for i, s in enumerate(series)]
    data = [_numbers(s["values"], "values") for s in series]

    if kind == "bar":
        labels = [str(v) for v in x]
        if len(series) == 1:
            plt.bar(labels, data[0], label=names[0])
        else:
            plt.multiple_bar(labels, data, labels=names)
        return

    numeric_x = all(isinstance(v, Number) and not isinstance(v, bool) for v in x)
    xs = x if numeric_x else list(range(len(x)))
    for name, ys in zip(names, data):
        (plt.scatter if kind == "scatter" else plt.plot)(xs, ys, label=name)
    if not numeric_x:
        plt.xticks(xs, [str(v) for v in x])


@register_widget("show_chart")
class ChartWidget(ToolWidget):
    DEFAULT_CSS = """
    ChartWidget { border: round $success 60%; }
    ChartWidget PlotextPlot { height: 18; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="body")
        yield PlotextPlot(id="plot")

    def on_mount(self) -> None:
        self.query_one(PlotextPlot).display = False

    def on_start(self) -> None:
        self.show(Text("📈 Drawing a chart…", style="dim italic"))  # skeleton

    def on_end(self, args: dict[str, Any]) -> None:
        super().on_end(args)
        plot = self.query_one(PlotextPlot)
        try:
            draw_chart(plot.plt, args)
        except (ValueError, TypeError) as exc:
            plot.display = False
            self.show(Text(f"📈 Could not draw chart: {exc}", style="red"))
            return
        self.show(Text(""))
        self.query_one("#body").display = False
        plot.display = True
        plot.refresh(layout=True)
