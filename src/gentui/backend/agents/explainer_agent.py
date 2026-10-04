"""Sample sub-agent: explains shell commands in plain English. One file + one decorator."""

from strands import Agent
from strands_harness import create_harness

from gentui.backend.config import get_settings
from gentui.backend.models import make_model
from gentui.backend.registry import register_agent


@register_agent()  # default: the orchestrator reads the answer and replies to the user
def explainer_agent() -> Agent:
    return create_harness(
        model=make_model(),
        effort=get_settings().effort,
        name="explainer_agent",
        callback_handler=None,
        description=(
            "Explains what a shell command does, flag by flag, in plain English. "
            "Input: the command line to explain. Never runs anything."
        ),
        instructions=(
            "You explain shell commands to beginners: one short summary sentence, then a "
            "bullet per flag or pipe stage. Mention anything risky. Never run anything."
        ),
        builtin_tools=[], builtin_plugins=[], background_tasks=False, memory=False,
        session=False, skills=False, context_manager=False, caching=False,
    )
