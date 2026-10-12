"""A judge that is a Strands agent: an LLM reads both answers and returns a structured verdict.

The same job as the built-in `ollama:<model>` judge, but you control the model and the instructions, and any Strands
model provider works. Needs: pip install 'gentui[strands,harness,ollama]' (and a running, signed-in Ollama for the
default model). Set GENTUI_JUDGE_MODEL to use another model.
"""

import os

from pydantic import BaseModel, Field
from strands_harness import create_harness

from gentui.judge import ollama_prompt
from gentui.plugins import register_judge

INSTRUCTIONS = """You compare two answers (A and B) that two versions of an AI agent gave to the same prompt.
Judge whether they match in substance: the same facts and numbers, the same conclusion, the same actions (tool calls).
Ignore wording, order, length and formatting. 1 = same in substance, 0 = different or contradicting.
In `reason`, name the key difference in one or two short sentences."""


class Verdict(BaseModel):
    score: float = Field(ge=0, le=1)
    reason: str


def make_judge():
    return create_harness(
        model=os.environ.get("GENTUI_JUDGE_MODEL", "ollama/gpt-oss:120b-cloud"),
        instructions=INSTRUCTIONS,
        builtin_tools=[], memory=False, session=False, skills=False,
    )


@register_judge("strands")
async def strands_judge(case):
    judge = make_judge()  # a fresh agent per case, so one verdict never leaks into the next
    verdict = await judge.structured_output_async(Verdict, ollama_prompt(case))
    return {"score": verdict.score, "reason": verdict.reason}
