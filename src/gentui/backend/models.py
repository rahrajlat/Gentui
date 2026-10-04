"""Model factory: the one place that decides which LLM backs the agents.

Returns a "<provider>/<model>" string, which create_harness() resolves itself.
Need custom endpoints or credentials? Return a strands Model instance here instead;
nothing else in the codebase changes.
"""

from gentui.backend.config import Settings, get_settings


def make_model(settings: Settings | None = None) -> str:
    return (settings or get_settings()).model
