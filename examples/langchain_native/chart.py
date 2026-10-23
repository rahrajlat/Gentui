"""Charts. The agent gets data from a tool, then calls `show_chart`; Gentui draws it in the terminal.
`show_chart` follows Gentui's tool contract (docs/tool-contract.md): its arguments are the chart.

Try: "Chart the monthly sales as a bar chart"
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from gentui import GentUI

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


# reasoning=True makes the Ollama model return its thinking, so Gentui can show it
agent = create_agent(init_chat_model("ollama:gpt-oss:120b-cloud", reasoning=True), tools=[get_sales, show_chart])

if __name__ == "__main__":
    GentUI.from_langchain(agent).run()
