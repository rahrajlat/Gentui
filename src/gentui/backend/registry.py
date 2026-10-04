"""Plugin registry: the single place tools and sub-agents are collected.

Adding a capability = write one file under tools/ or agents/ and decorate it.
The orchestrator calls `discover()` and gets everything automatically.
"""

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from strands import Agent

_tools: list[Any] = []
_agent_factories: list[tuple[Callable[[], Agent], dict[str, Any]]] = []


def register_tool(tool_obj: Any) -> Any:
    """Decorator: stack *above* Strands' @tool.

        @register_tool
        @tool
        def my_tool(...): ...
    """
    _tools.append(tool_obj)
    return tool_obj


def register_agent(**as_tool_kwargs: Any) -> Callable[[Callable[[], Agent]], Callable[[], Agent]]:
    """Decorator for a function that builds a sub-agent (an Agent with `name` and `description`).

        @register_agent(delegate=True)
        def my_agent() -> Agent: ...

    It becomes a tool of the orchestrator via Agent.as_tool(**as_tool_kwargs). Use
    `delegate=True` when the sub-agent's reply should end the turn (the orchestrator then
    makes no further model call). Factories are lazy: the model is only built when the
    orchestrator is created.
    """

    def deco(factory: Callable[[], Agent]) -> Callable[[], Agent]:
        _agent_factories.append((factory, as_tool_kwargs))
        return factory

    return deco


def discover() -> list[Any]:
    """Import every module in tools/ and agents/ (which registers them) and return all tools."""
    for pkg_name in ("gentui.backend.tools", "gentui.backend.agents"):
        pkg = importlib.import_module(pkg_name)
        for m in pkgutil.iter_modules(pkg.__path__):
            importlib.import_module(f"{pkg_name}.{m.name}")
    return [*_tools, *(f().as_tool(**kw) for f, kw in _agent_factories)]
