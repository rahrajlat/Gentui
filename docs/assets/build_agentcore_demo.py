"""Regenerate agentcore-demo.gif: Gentui in front of an agent hosted on Amazon Bedrock AgentCore Runtime.

    uv run --with pillow python docs/assets/build_agentcore_demo.py

Like demo.gif, the TUI is real and driven by a scripted backend (no AWS account or LLM needed). The shell
intro is drawn to match the window frame.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ag_ui.core import (Interrupt, ReasoningEndEvent, ReasoningMessageContentEvent, ReasoningMessageEndEvent,
                        ReasoningMessageStartEvent, ReasoningStartEvent, RunFinishedEvent, RunFinishedInterruptOutcome,
                        RunStartedEvent)
from PIL import Image, ImageDraw, ImageFont

from build_assets import BG, FONTS, OUT, Driver, GentuiApp, Config, say, to_p, tool, screen_image

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/ops_agent-Zk3fQ9"


def shell_image(lines: list[tuple[str, str]], size: tuple[int, int], font_size: int = 20) -> Image.Image:
    """A terminal window of `size` showing `lines` as (colour, text), in the same chrome as screen_image."""
    font = ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{FONTS[(False, False)]}", font_size)
    bold = ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{FONTS[(True, False)]}", font_size)
    ascent, descent = font.getmetrics()
    ch = ascent + descent
    img = Image.new("RGB", size, (38, 40, 46))
    draw = ImageDraw.Draw(img)
    for i, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        draw.ellipse((18 + i * 26, 14, 34 + i * 26, 30), fill=colour)
    draw.text((size[0] // 2, 22), "Gentui", font=bold, fill=(200, 204, 212), anchor="mm")
    draw.rectangle((14, 44, size[0] - 15, size[1] - 15), fill=BG)
    for i, (colour, text) in enumerate(lines):
        draw.text((30, 60 + i * ch), text, font=font, fill=colour)
    return img


async def build() -> None:
    driver = Driver()
    welcome = ("◈ Welcome to Gentui!\n\n  /help for commands · /quit to exit · /dev for the event inspector\n"
               "  backend: Amazon Bedrock AgentCore Runtime (ops_agent, us-east-1)")
    cfg = Config(splash=False, show_time=True, agentcore_arn=ARN, welcome=welcome)
    app = GentuiApp(driver, cfg)
    shots: list[tuple[Image.Image, int]] = []

    async with app.run_test(size=(100, 34)) as pilot:
        async def shot(ms: int) -> None:
            await pilot.pause(0.5)
            shots.append((screen_image(app), ms))

        question = "which disks are almost full on this box?"
        prompt = app.query_one("#prompt")
        prompt.value = question[:16]
        await shot(800)
        prompt.value = question
        await shot(900)
        await pilot.press("enter")
        await driver.push(0, RunStartedEvent(thread_id="t", run_id="r1"), ReasoningStartEvent(message_id="r"),
                          ReasoningMessageStartEvent(message_id="r", role="reasoning"),
                          ReasoningMessageContentEvent(message_id="r", delta="Disk usage is a df question. I'll propose df, sorted by use%, and let the user approve it."))
        await shot(1500)

        cmd = "df -h --output=target,pcent | sort -k2 -nr | head -5"
        await driver.push(0, ReasoningMessageEndEvent(message_id="r"), ReasoningEndEvent(message_id="r"),
                          *say("a1", "Streaming from your **AgentCore runtime**. I'd check disk usage with:"),
                          *tool("c1", "propose_command", {"command": cmd, "explanation": "Shows the five fullest mounts.", "risk": "safe"}, "Proposal shown to the user. It has NOT been run. Stop and wait for the user's decision."),
                          RunFinishedEvent(thread_id="t", run_id="r1", outcome=RunFinishedInterruptOutcome(interrupts=[
                              Interrupt(id="approve-c1", reason="tool_call", tool_call_id="c1", message="Run this command?")])),
                          None)
        await shot(2800)

        app.query_one("#approve").press()
        out = "/var/lib/docker  91%\n/               78%\n/home           64%\n/boot           22%\n/run             3%\n"
        await driver.push(1, RunStartedEvent(thread_id="t", run_id="r2"),
                          *tool("c2", "run_command", {"approval_id": "c1"}, json.dumps({"command": cmd, "exit_code": 0, "timed_out": False, "truncated": False, "output": out})),
                          *say("a2", "`/var/lib/docker` is at **91%**. Worth pruning old images before it fills up."),
                          RunFinishedEvent(thread_id="t", run_id="r2"), None)
        await shot(3200)

    size = shots[0][0].size
    cyan, grey, white = (79, 214, 200), (139, 147, 161), (230, 233, 239)
    typed = "gentui " + ARN
    intro: list[tuple[Image.Image, int]] = [
        (shell_image([(grey, "$ pip install gentui boto3")], size), 700),
        (shell_image([(grey, "$ pip install gentui boto3"), (cyan, "Successfully installed gentui")], size), 900),
    ]
    base = [(grey, "$ pip install gentui boto3"), (cyan, "Successfully installed gentui")]
    for text in (typed[:7], typed[:40], typed):
        intro.append((shell_image(base + [(white, "$ " + text)], size), 450 if text != typed else 1100))
    shots = intro + shots

    frames = [to_p(img) for img, _ in shots]
    path = OUT / "agentcore-demo.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[ms for _, ms in shots], loop=0, optimize=True, disposal=2)
    print(path, frames[0].size, len(frames), "frames", path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(build(), timeout=120))
