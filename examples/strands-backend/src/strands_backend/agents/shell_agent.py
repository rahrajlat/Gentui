"""Shell sub-agent: turns natural language into ONE proposed shell command."""

from strands import Agent
from strands_harness import create_harness

from strands_backend.config import get_settings
from strands_backend.models import make_model
from strands_backend.registry import register_agent
from strands_backend.tools.shell import detect_shell, propose_command


# delegate=True: once a command is proposed the turn ends and the user decides.
@register_agent(delegate=True)
def shell_agent() -> Agent:
    return create_harness(
        model=make_model(),
        effort=get_settings().effort,
        name="shell_agent",
        callback_handler=None,
        description=(
            "Turns a natural-language request into a single shell command proposal "
            "for the user to approve. Pass the user's request as the input."
        ),
        instructions=(
            f"You write shell commands. The user's shell is {detect_shell()}.\n"
            "Always answer by calling propose_command exactly once, with a command in that "
            "shell's syntax, a one-sentence explanation and an honest risk level. "
            "Prefer read-only commands. Never chain unrelated commands. "
            "No interactive programs (no editors, no pagers). "
            "After propose_command returns, reply with one short sentence."
        ),
        tools=[propose_command],
        background_tasks=False,
        # Bare agent: its only ability is proposing.
        builtin_tools=[], builtin_plugins=[], memory=False, session=False,
        skills=False, context_manager=False, caching=False,
    )
