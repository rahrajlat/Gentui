"""Builds the orchestrator agent from everything in the registry."""

from strands import Agent
from strands_harness import create_harness

from gentui.backend.config import get_settings
from gentui.backend.models import make_model
from gentui.backend.registry import discover
from gentui.backend.tools.shell import detect_shell


def build_orchestrator() -> Agent:
    return create_harness(
        model=make_model(),
        effort=get_settings().effort,
        name="orchestrator",
        callback_handler=None,  # no stdout printing; the adapter streams events instead
        instructions=(
            f"You are a terminal assistant. The user's shell is {detect_shell()}.\n"
            "Shell work follows a strict approval flow:\n"
            "1. For anything that needs a shell command, call the shell_agent tool with the user's "
            "request. It shows the user a proposed command with Approve / Edit / Reject buttons. "
            "Never invent command output yourself.\n"
            "2. After proposing, the turn ends: the user decides. Do not run anything yet.\n"
            "3. Only when the user's next message says a command was approved, call run_command with "
            "the approval_id given in that message (never a command). Then summarise the output briefly.\n"
            "4. If the user rejected it, do not run it; ask what they would prefer instead.\n"
            "Use show_table to present several items that have several attributes. Use explainer_agent when asked what a command does.\n"
            "For tasks with several steps, first call todo_write to lay out the plan, and update it "
            "as you progress (one step in_progress at a time). Skip it for simple one-step requests.\n"
            "Keep replies short."
        ),
        tools=discover(),
        background_tasks=False,  # no injected `_background_execution` tool arg
        # Harness features are enabled deliberately. The built-in `shell` stays OFF: the only
        # way to a command is propose -> approve -> run_command.
        builtin_tools=[],
        builtin_plugins=["todos"],  # todo_write tool -> shared plan state
        memory=False, session=False, skills=False, context_manager=False, caching=False,
    )
