"""A judge with no model: did both versions call the same tools with the same arguments?

Useful when you change a prompt or a model and want to know whether the agent still does the same *actions*, whatever
it says about them. Each side's tool calls are `{"name", "args", "result"}`.
"""

from gentui.plugins import register_judge


def calls(tools: list[dict]) -> list[str]:
    return [f"{t['name']}({t.get('args') or ''})" for t in tools]


@register_judge("same-tools")
def same_tools(case):
    left, right = calls(case.left_tools), calls(case.right_tools)
    if not left and not right:
        return {"score": 1.0, "reason": "no tool calls on either side"}
    if left == right:
        return {"score": 1.0, "reason": f"the same {len(left)} tool call(s), in the same order"}
    names_left = [t["name"] for t in case.left_tools]
    names_right = [t["name"] for t in case.right_tools]
    if sorted(names_left) == sorted(names_right):
        return {"score": 0.7, "reason": "same tools, but the arguments or the order differ"}
    missing = sorted(set(names_left) - set(names_right))
    extra = sorted(set(names_right) - set(names_left))
    return {"score": 0.2, "reason": f"different tools; A only: {missing or '-'}; B only: {extra or '-'}"}
