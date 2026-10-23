"""A tool call that waits for your approval. `delete_file` pauses before it runs: Approve runs it, Reject cancels it
(the model is told you refused). `list_files` is not protected.

The files are pretend (an in-memory dict), so nothing on your disk is touched.
Try: "List the files, then delete notes.txt"
"""

from strands import tool
from strands_harness import create_harness

from gentui import GentUI
from gentui.adapters.strands import approval_hook, ollama_model

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


agent = create_harness(
    model=ollama_model("gpt-oss:120b-cloud"),  # unlike model="ollama/...", this one streams the thinking
    tools=[list_files, delete_file],
    builtin_tools=[], memory=False, session=False, skills=False,
)
agent.add_hook(approval_hook("list_files"))  # the agent pauses here until you decide

if __name__ == "__main__":
    GentUI.from_strands(agent).run()
