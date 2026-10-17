"""Gentui: a terminal client for any AG-UI agent backend.

    from gentui import GentUI
    GentUI.from_strands(agent).run()      # a Strands agent, in this process, no server
    GentUI.from_langchain(agent).run()    # a LangChain / LangGraph agent, same idea
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gentui.config import Config

__all__ = ["GentUI"]


class GentUI:
    """The terminal UI around a client that yields AG-UI events. Importing this module is cheap: Textual
    and the rest are loaded when you build or run the app."""

    def __init__(self, adapter: Any, config: "Config | None" = None, **options: Any) -> None:
        """`adapter` is any client with `run(thread_id, text, forwarded_props, resume)` yielding AG-UI events,
        e.g. `StrandsAGUIAdapter(agent)`. `options` are `Config` fields (theme, title, dev_pane...) and win over
        the config file."""
        self.adapter = adapter
        self._config, self._options = config, options

    @classmethod
    def from_strands(cls, agent: Any, config: "Config | None" = None, **options: Any) -> "GentUI":
        """Chat with an instantiated Strands `Agent` in this process: no FastAPI, no HTTP, no second process."""
        from gentui.adapters.strands import StrandsAGUIAdapter

        return cls(StrandsAGUIAdapter(agent), config, **options)

    @classmethod
    def from_langchain(cls, agent: Any, config: "Config | None" = None, **options: Any) -> "GentUI":
        """Chat with a LangChain / LangGraph agent (a compiled graph) in this process: no server, no HTTP."""
        from gentui.adapters.langchain import LangChainAGUIAdapter

        return cls(LangChainAGUIAdapter(agent), config, **options)

    def build(self):
        """The Textual app (for `run_test` or embedding); `run()` builds and runs it."""
        from dataclasses import replace

        from gentui.config import load_config
        from gentui.tui.app import GentuiApp

        label = getattr(self.adapter, "label", None) or type(self.adapter).__name__ + " (in-process, no server)"
        if self._config is None:
            config = load_config(None, url=label, **self._options)
        else:
            config = replace(self._config, **self._options)
        return GentuiApp(self.adapter, config)

    def run(self, record: str | None = None, prompts: list[str] | None = None) -> None:
        """Open the UI. `record` saves the session to NAME.json; `prompts` are sent one after another."""
        from gentui.cli import _run

        _run(self.build(), record, prompts)
