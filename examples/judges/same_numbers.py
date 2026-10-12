"""A judge with no model: do both answers state the same numbers?

Free, instant and deterministic, so it is good for answers that are mostly figures (sizes, counts, prices).
It scores the share of numbers that appear on both sides.
"""

import re

from gentui.plugins import register_judge

NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}


@register_judge("same-numbers")
def same_numbers(case):
    left, right = numbers(case.left), numbers(case.right)
    if not left and not right:
        return {"score": 1.0, "reason": "neither answer contains numbers"}
    shared = left & right
    score = len(shared) / len(left | right)
    only_left, only_right = sorted(left - right)[:5], sorted(right - left)[:5]
    reason = f"{len(shared)} of {len(left | right)} numbers match"
    if only_left or only_right:
        reason += f"; only in A: {only_left or '-'}; only in B: {only_right or '-'}"
    return {"score": score, "reason": reason}
