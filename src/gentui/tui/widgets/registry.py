"""Maps tool name -> widget class. Unknown tools fall back to the generic card.

Adding a widget = write a ToolWidget subclass and decorate it:

    @register_widget("show_table")
    class TableWidget(ToolWidget): ...
"""

from collections.abc import Callable

from gentui.tui.widgets.base import ToolWidget

_WIDGETS: dict[str, type[ToolWidget]] = {}


def register_widget(*tool_names: str) -> Callable[[type[ToolWidget]], type[ToolWidget]]:
    def deco(cls: type[ToolWidget]) -> type[ToolWidget]:
        for name in tool_names:
            _WIDGETS[name] = cls
        return cls

    return deco


def widget_for(call_id: str, tool_name: str) -> ToolWidget:
    from gentui.tui.widgets.generic import GenericToolWidget  # avoid circular import

    return _WIDGETS.get(tool_name, GenericToolWidget)(call_id, tool_name)
