"""A tool call that waits for your approval. `delete_file` pauses before it runs: Approve runs it, Reject skips it
(the model is told you refused). `list_files` is not protected.

The files are pretend (an in-memory dict), so nothing on your disk is touched.
Try: "List the files, then delete notes.txt"
"""

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from gentui import GentUI
from gentui.adapters.langchain import approval_middleware

FILES = {"notes.txt": "buy milk", "todo.md": "- ship it"}


@tool
def list_files() -> list[str]:
    """List the files."""
    return sorted(FILES)


@tool
def delete_file(name: str) -> str:
    """Delete a file by name."""
    FILES.pop(name)
    return f"deleted {name}"


agent = create_agent(
    init_chat_model("ollama:gpt-oss:120b-cloud"),
    tools=[list_files, delete_file],
    middleware=[approval_middleware("delete_file")],  # the agent pauses here until you decide
)

if __name__ == "__main__":
    GentUI.from_langchain(agent).run()
