"""Charts. The agent gets data from a tool, then calls `show_chart`; Gentui draws it in the terminal.
`show_chart` follows Gentui's tool contract (docs/tool-contract.md): its arguments are the chart.

Try: "Chart the monthly sales as a bar chart"
"""

from strands import tool
from strands_harness import create_harness

from gentui import GentUI
from gentui.adapters.strands import ollama_model

SALES = {"Jan": 120, "Feb": 150, "Mar": 90, "Apr": 180, "May": 210}


@tool
def get_sales() -> dict:
    """Monthly sales figures."""
    return SALES


@tool
def show_chart(type: str, title: str, x: list, series: list[dict], x_label: str = "", y_label: str = "") -> str:
    """Show a chart to the user. type is line, bar, scatter or histogram; series is [{"name": str, "values": [numbers]}].
    Use real data from tools, never invent numbers."""
    return "chart shown"


agent = create_harness(
    model=ollama_model("gpt-oss:120b-cloud"),  # unlike model="ollama/...", this one streams the thinking
    tools=[get_sales, show_chart],
    builtin_tools=[], memory=False, session=False, skills=False,
)

if __name__ == "__main__":
    GentUI.from_strands(agent).run()
