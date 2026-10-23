"""A tool call. Gentui shows the tool name, its arguments, "running", then the real result.

Try: "Calculate 125 * 42"
"""

import time

from strands import tool
from strands_harness import create_harness

from gentui import GentUI
from gentui.adapters.strands import ollama_model


@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    time.sleep(1)  # so you can see the "running" state
    return a * b


agent = create_harness(
    model=ollama_model("gpt-oss:120b-cloud"),  # unlike model="ollama/...", this one streams the thinking
    tools=[multiply],
    builtin_tools=[], memory=False, session=False, skills=False,
)

if __name__ == "__main__":
    GentUI.from_strands(agent).run()
