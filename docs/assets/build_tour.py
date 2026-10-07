"""Regenerate tour.gif: a feature tour of Gentui (AgentCore launch, slash commands, chain of thought, memory,
plan, approval, output, table, chart, event inspector, themes).

    uv run --with pillow python docs/assets/build_tour.py

The TUI is real and driven by a scripted backend (no AWS account or LLM needed); captions are drawn on top.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ag_ui.core import (Interrupt, ReasoningEndEvent, ReasoningMessageContentEvent, ReasoningMessageEndEvent,
                        ReasoningMessageStartEvent, ReasoningStartEvent, RunFinishedEvent, RunFinishedInterruptOutcome,
                        RunStartedEvent, StateSnapshotEvent, StateDeltaEvent)
from PIL import Image, ImageDraw, ImageFont

from build_assets import BG, FONTS, OUT, Config, Driver, GentuiApp, say, screen_image, to_p, tool
from build_agentcore_demo import ARN, shell_image

CAP_BG, CAP_FG, ACCENT = (24, 26, 32), (230, 233, 239), (79, 214, 200)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"


def captioned(img: Image.Image, text: str, step: str) -> Image.Image:
    """`img` with a caption bar underneath."""
    bar = 64
    out = Image.new("RGB", (img.width, img.height + bar), CAP_BG)
    out.paste(img, (0, 0))
    draw = ImageDraw.Draw(out)
    font = ImageFont.truetype(FONT, 24)
    draw.rectangle((0, img.height, img.width, img.height + 2), fill=ACCENT)
    draw.text((24, img.height + bar // 2 + 1), step, font=font, fill=ACCENT, anchor="lm")
    draw.text((24 + font.getlength(step) + 20, img.height + bar // 2 + 1), text, font=font, fill=CAP_FG, anchor="lm")
    return out


def plan(*states: str) -> list[dict]:
    items = ["check the python version", "check disk usage", "summarise"]
    return [{"content": c, "status": s} for c, s in zip(items, states)]


async def build() -> None:
    driver = Driver()
    welcome = ("◈ Welcome to Gentui!\n\n  /help for commands · /quit to exit · /dev for the event inspector\n"
               "  backend: Amazon Bedrock AgentCore Runtime (ops_agent, us-east-1)")
    app = GentuiApp(driver, Config(splash=False, show_time=True, agentcore_arn=ARN, welcome=welcome))
    shots: list[tuple[Image.Image, int]] = []
    step = 0
    cap = {"text": ""}

    async with app.run_test(size=(100, 38)) as pilot:
        async def shot(ms: int, text: str | None = None, new_step: bool = False) -> None:
            nonlocal step
            if text is not None:
                cap["text"] = text
            if new_step:
                step += 1
            await pilot.pause(0.5)
            shots.append((captioned(screen_image(app), cap["text"], f"{step}/10"), ms))

        prompt = app.query_one("#prompt")

        async def type_(text: str, ms: int = 1000) -> None:
            prompt.value = text[: len(text) // 2]
            await shot(500)
            prompt.value = text
            await shot(ms)

        # 1. slash commands
        await shot(1200, "Any AG-UI backend, local or on AgentCore", new_step=True)
        await type_("/help", 700)
        await pilot.press("enter")
        await shot(2400, "Slash commands: /new /export_md /theme /dev /reasoning", new_step=True)

        # 2. reasoning + memory + plan
        await type_("is this box healthy? check python and disk", 700)
        await pilot.press("enter")
        await driver.push(0, RunStartedEvent(thread_id="t", run_id="r1"), ReasoningStartEvent(message_id="r"),
                          ReasoningMessageStartEvent(message_id="r", role="reasoning"),
                          ReasoningMessageContentEvent(message_id="r", delta="Two checks: the Python version, then disk usage. I'll plan it, "
                                                       "and propose one command at a time so the user can review each."))
        await shot(1800, "Streaming chain of thought, collapsible", new_step=True)
        await driver.push(0, ReasoningMessageEndEvent(message_id="r"), ReasoningEndEvent(message_id="r"),
                          *tool("m1", "search_memory", {"query": "disk usage threshold"}, "User prefers alerts above 85% full."),
                          StateSnapshotEvent(snapshot={"plan": plan("in_progress", "pending", "pending")}),
                          *say("a1", "Starting with the **Python version**."))
        await shot(2200, "Long-term memory recall and a live plan checklist", new_step=True)

        cmd = "python3 --version && df -h / | tail -1"
        await driver.push(0, *tool("c1", "propose_command", {"command": cmd, "explanation": "Prints the Python version and root disk usage.", "risk": "safe"},
                                   "Proposal shown to the user. It has NOT been run. Stop and wait for the user's decision."),
                          RunFinishedEvent(thread_id="t", run_id="r1", outcome=RunFinishedInterruptOutcome(interrupts=[
                              Interrupt(id="approve-c1", reason="tool_call", tool_call_id="c1", message="Run this command?")])),
                          None)
        await shot(2800, "Human-in-the-loop: nothing runs until you approve", new_step=True)

        app.query_one("#approve").press()
        out = "Python 3.12.4\n/dev/nvme0n1p2  200G  156G   44G  78% /\n"
        await driver.push(1, RunStartedEvent(thread_id="t", run_id="r2"),
                          *tool("c2", "run_command", {"approval_id": "c1"}, json.dumps({"command": cmd, "exit_code": 0, "timed_out": False, "truncated": False, "output": out})),
                          StateDeltaEvent(delta=[{"op": "replace", "path": "/plan", "value": plan("completed", "completed", "in_progress")}]),
                          *say("a2", "Python is **3.12.4** and `/` is **78%** full: healthy, under your 85% threshold."),
                          StateDeltaEvent(delta=[{"op": "replace", "path": "/plan", "value": plan("completed", "completed", "completed")}]),
                          RunFinishedEvent(thread_id="t", run_id="r2"), None)
        await shot(3200, "Command output with exit-code badge, plan completed", new_step=True)

        # 3. table + chart on a fresh chat
        await type_("/new", 500)
        await pilot.press("enter")
        await type_("show disk usage per mount as a table and a chart", 700)
        await pilot.press("enter")
        mounts = ["/var/lib/docker", "/", "/home", "/boot", "/run"]
        pct = [91, 78, 64, 22, 3]
        await driver.push(2, RunStartedEvent(thread_id="t2", run_id="r3"),
                          *tool("t1", "show_table", {"title": "Disk usage", "columns": ["Mount", "Used %", "Size"],
                                                     "rows": [[m, f"{p}%", s] for m, p, s in zip(mounts, pct, ["120G", "200G", "500G", "1G", "16G"])]}, "ok"))
        await shot(2200, "Generative widgets: tables from tool calls", new_step=True)
        await driver.push(2, *tool("c3", "show_chart", {"type": "bar", "title": "Used % per mount", "x": mounts,
                                                         "series": [{"name": "Used %", "values": pct}], "y_label": "%"}, "ok"),
                          *say("a3", "Same data as a chart. `/var/lib/docker` stands out."),
                          RunFinishedEvent(thread_id="t2", run_id="r3"), None)
        await shot(3600, "...and terminal charts: bar, line, scatter, histogram", new_step=True)

        # 4. event inspector, themes
        await type_("/dev", 500)
        await pilot.press("enter")
        await shot(3200, "/dev: the raw AG-UI events, exactly as sent", new_step=True)
        await type_("/dev", 400)
        await pilot.press("enter")
        await type_("/theme", 500)
        await pilot.press("enter")
        await shot(1500)
        names = sorted(app.available_themes)
        other = next((n for n in ("dracula", "nord", "tokyo-night", "gruvbox") if n in names), names[0])
        await type_(f"/theme {other}", 400)
        await pilot.press("enter")
        await shot(3000, f"Themes and your own CSS: /theme {other}", new_step=True)

    size = shots[0][0].size
    grey, cyan, white = (139, 147, 161), (79, 214, 200), (230, 233, 239)
    typed = "gentui " + ARN
    head = [(grey, "$ pip install 'gentui[agentcore]'"), (cyan, "Successfully installed gentui boto3")]
    intro = [(captioned(shell_image(head[:1], (size[0], size[1] - 66)), "pip install gentui. Bring your agent, speak AG-UI.", "0/10"), 900),
             (captioned(shell_image(head, (size[0], size[1] - 66)), "pip install gentui. Bring your agent, speak AG-UI.", "0/10"), 900)]
    for text in (typed[:7], typed[:44], typed):
        intro.append((captioned(shell_image(head + [(white, "$ " + text)], (size[0], size[1] - 66)), "Point it at an AgentCore runtime ARN or any URL", "0/10"), 450 if text != typed else 1100))
    shots = intro + shots

    frames = [to_p(img) for img, _ in shots]
    path = OUT / "tour.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[ms for _, ms in shots], loop=0, optimize=True, disposal=2)
    print(path, frames[0].size, len(frames), "frames", path.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(build(), timeout=180))
