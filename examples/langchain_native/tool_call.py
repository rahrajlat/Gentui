"""A tool call. Gentui shows the tool name, its arguments, "running", then the real result.

Try: "Calculate 125 * 42"
"""

import time

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from gentui import GentUI


@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    time.sleep(1)  # so you can see the "running" state
    return a * b


# reasoning=True makes the Ollama model return its thinking, so Gentui can show it
agent = create_agent(init_chat_model("ollama:gpt-oss:120b-cloud", reasoning=True), tools=[multiply])

if __name__ == "__main__":
    GentUI.from_langchain(agent).run()
