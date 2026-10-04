"""Regenerate the README images: logo.png, hero.gif (splash animation) and demo.gif (the TUI in use).

    uv run --with pillow python docs/assets/build_assets.py

The logo and hero use the same code as the app's splash (`gentui.tui.branding`). The demo is recorded
from the real TUI driven by a scripted backend, so it is deterministic and needs no LLM.
"""

import asyncio
import io
import json
import re
from pathlib import Path

from ag_ui.core import (
    ReasoningEndEvent, ReasoningMessageContentEvent, ReasoningMessageEndEvent, ReasoningMessageStartEvent,
    ReasoningStartEvent, RunFinishedEvent, RunStartedEvent, TextMessageContentEvent, TextMessageEndEvent,
    TextMessageStartEvent, ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent, ToolCallStartEvent,
)
from ag_ui.core import Interrupt, RunFinishedInterruptOutcome
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from gentui.config import Config
from gentui.tui import branding
from gentui.tui.app import GentuiApp

OUT = Path(__file__).parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
BG = (20, 22, 27)  # the gentui theme background, #14161B
MUTED = (139, 147, 161)


# -- drawing a Rich Text on a character grid -----------------------------------------------------


def draw_rich(draw: ImageDraw.ImageDraw, text, origin, font, cell) -> None:
    console = Console(width=200, color_system="truecolor", file=io.StringIO())
    x0, y0 = origin
    cw, ch = cell
    col = row = 0
    for seg in console.render(text, console.options.update(width=200)):
        for char in seg.text:
            if char == "\n":
                row, col = row + 1, 0
                continue
            colour = seg.style.color.get_truecolor() if seg.style and seg.style.color else None
            if char == "█" and colour:  # solid blocks as exact rectangles: no anti-aliased seams between cells
                px, py = x0 + col * cw, y0 + row * ch
                draw.rectangle((px, py, px + cw - 1, py + ch - 1), fill=tuple(colour))
            elif char != " " and colour:
                draw.text((x0 + col * cw, y0 + row * ch), char, font=font, fill=tuple(colour), anchor="la")
            col += 1


def metrics(size: int):
    font = ImageFont.truetype(FONT, size)
    ascent, descent = font.getmetrics()
    return font, (round(font.getlength("█")), ascent + descent)


def splash_image(t: float, size=32, static=False) -> Image.Image:
    from rich.text import Text

    font, (cw, ch) = metrics(size)
    wordmark = branding.WORDMARK_BIG
    cols = max(len(line) for line in wordmark.splitlines())
    pad = 60
    img = Image.new("RGB", (cols * cw + pad * 2, 6 * ch + 150), BG)
    draw = ImageDraw.Draw(img)
    logo = branding.logo_static(wordmark) if static else branding.logo_frame(wordmark, t)
    draw_rich(draw, logo, (pad, pad), font, (cw, ch))
    tag_font, (tw, th) = metrics(22)
    tagline = f"{branding.MARK}  {branding.TAGLINE}"
    typed = len(tagline) if static else int(max(0.0, t - 0.8) * 45)
    shown = tagline[:typed]
    if shown:
        text = Text(shown, style=f"{'#4FD6C8'}")
        # tagline in muted grey with a teal mark
        grey = Text(shown[3:], style="#8B93A1")
        full = Text(shown[:3], style="#4FD6C8") + grey if len(shown) > 3 else text
        draw_rich(draw, full, (pad + 2, pad + 6 * ch + 28), tag_font, (tw, th))
    return img


# -- logo.png (transparent, for the README header) -------------------------------------------------


def build_logo() -> None:
    from rich.text import Text

    font, (cw, ch) = metrics(40)
    wordmark = branding.WORDMARK_BIG
    cols = max(len(line) for line in wordmark.splitlines())
    pad = 24
    tag_font, (tw, th) = metrics(26)
    img = Image.new("RGBA", (cols * cw + pad * 2, 6 * ch + th + pad * 3), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_rich(draw, branding.logo_static(wordmark), (pad, pad), font, (cw, ch))
    tagline = f"{branding.MARK}  {branding.TAGLINE}"
    width = round(tag_font.getlength("█")) * len(tagline)
    line = Text(tagline[:3], style="#4FD6C8") + Text(tagline[3:], style="#7B8494")
    draw_rich(draw, line, ((img.width - width) // 2, pad * 2 + 6 * ch), tag_font, (tw, th))
    img.save(OUT / "logo.png", optimize=True)
    print("logo.png", img.size)


# -- hero.gif: the splash animation, then the finished logo held ------------------------------------


def to_p(img: Image.Image) -> Image.Image:
    return img.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def build_hero() -> None:
    fps = 20
    frames, durations = [], []
    for i in range(int(2.8 * fps)):
        frames.append(to_p(splash_image(i / fps, size=26)))
        durations.append(1000 // fps)
    frames.append(to_p(splash_image(0, size=26, static=True)))  # the finished logo, held, then the loop restarts
    durations.append(2600)
    frames[0].save(OUT / "hero.gif", save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=True, disposal=2)
    print("hero.gif", frames[0].size, len(frames), "frames")


# -- demo.gif: the real TUI, scripted -------------------------------------------------------------


class Driver:
    """A client the script controls: each run() yields whatever the script pushes until `None`."""

    def __init__(self) -> None:
        self.queues: list[asyncio.Queue] = []
        self.calls = 0

    async def run(self, thread_id, text, forwarded_props=None, resume=None):
        queue: asyncio.Queue = asyncio.Queue()
        self.queues.append(queue)
        self.calls += 1
        while (event := await queue.get()) is not None:
            yield event

    async def push(self, run_index: int, *events) -> None:
        for _ in range(200):  # 10 s: fail loudly instead of hanging if the app never started that run
            if len(self.queues) > run_index:
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError(f"run {run_index} never started (runs so far: {len(self.queues)})")
        for event in events:
            await self.queues[run_index].put(event)


def tool(call_id, name, args, result=None):
    yield ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name)
    yield ToolCallArgsEvent(tool_call_id=call_id, delta=json.dumps(args))
    yield ToolCallEndEvent(tool_call_id=call_id)
    if result is not None:
        yield ToolCallResultEvent(message_id="m" + call_id, tool_call_id=call_id, content=result, role="tool")


def say(mid, text):
    yield TextMessageStartEvent(message_id=mid, role="assistant")
    yield TextMessageContentEvent(message_id=mid, delta=text)
    yield TextMessageEndEvent(message_id=mid)


FONTS = {
    (False, False): "DejaVuSansMono.ttf", (True, False): "DejaVuSansMono-Bold.ttf",
    (False, True): "DejaVuSansMono-Oblique.ttf", (True, True): "DejaVuSansMono-BoldOblique.ttf",
}


def screen_image(app: GentuiApp, size: int = 20) -> Image.Image:
    """Draw the app's current screen on a character grid, inside a simple terminal window frame."""
    fonts = {k: ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{v}", size) for k, v in FONTS.items()}
    ascent, descent = fonts[(False, False)].getmetrics()
    cw, ch = round(fonts[(False, False)].getlength("M")), ascent + descent
    strips = app.screen._compositor.render_strips()
    top, edge = 44, 14
    img = Image.new("RGB", (len(strips[0].text) * cw + edge * 2, len(strips) * ch + top + edge), (38, 40, 46))
    draw = ImageDraw.Draw(img)
    for i, colour in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):  # window buttons
        draw.ellipse((18 + i * 26, 14, 34 + i * 26, 30), fill=colour)
    title_font = fonts[(True, False)]
    draw.text((img.width // 2, 22), "Gentui", font=title_font, fill=(200, 204, 212), anchor="mm")

    def rgb(color, default):
        try:
            return tuple(color.get_truecolor()) if color is not None else default
        except Exception:  # noqa: BLE001 - a default/ANSI colour without a fixed value
            return default

    fg_default = (230, 233, 239)
    for y, strip in enumerate(strips):
        x = 0
        for seg in strip:
            style = seg.style
            fg, bg = rgb(style.color if style else None, fg_default), rgb(style.bgcolor if style else None, BG)
            if style and style.reverse:
                fg, bg = bg, fg
            if style and style.dim:
                fg = tuple((f + b) // 2 for f, b in zip(fg, bg))
            font = fonts[(bool(style and style.bold), bool(style and style.italic))]
            for char in seg.text:
                px, py = edge + x * cw, top + y * ch
                draw.rectangle((px, py, px + cw - 1, py + ch - 1), fill=bg)
                if char != " ":
                    draw.text((px, py), char, font=font, fill=fg, anchor="la")
                    if style and style.strike:
                        draw.line((px, py + ch // 2, px + cw, py + ch // 2), fill=fg)
                x += 1
    return img


async def build_demo() -> None:
    driver = Driver()
    app = GentuiApp(driver, Config(splash=False, show_time=True))
    shots: list[tuple[Image.Image, int]] = []

    async with app.run_test(size=(100, 34)) as pilot:
        async def shot(ms: int) -> None:
            await pilot.pause(0.5)
            shots.append((screen_image(app), ms))

        question = "what are the 5 largest files here?"
        prompt = app.query_one("#prompt")
        prompt.value = question[:14]
        await shot(900)
        prompt.value = question
        await shot(900)

        await pilot.press("enter")
        await driver.push(0, RunStartedEvent(thread_id="t", run_id="r1"), ReasoningStartEvent(message_id="r"),
                          ReasoningMessageStartEvent(message_id="r", role="reasoning"),
                          ReasoningMessageContentEvent(message_id="r", delta="The user wants the biggest files. I should propose a find command, sorted by size."))
        await shot(1500)

        cmd = "find . -type f -printf '%s %p\\n' | sort -nr | head -5"
        await driver.push(0, ReasoningMessageEndEvent(message_id="r"), ReasoningEndEvent(message_id="r"),
                          *say("a1", "Here's a command for the **5 largest files**:"),
                          *tool("c1", "propose_command", {"command": cmd, "explanation": "Lists the five largest files with their sizes.", "risk": "safe"}, "Proposal shown to the user. It has NOT been run. Stop and wait for the user's decision."),
                          RunFinishedEvent(thread_id="t", run_id="r1", outcome=RunFinishedInterruptOutcome(interrupts=[
                              Interrupt(id="approve-c1", reason="tool_call", tool_call_id="c1", message="Run this command?")])),
                          None)
        await shot(2600)

        app.query_one("#approve").press()  # (a click can miss when the card has scrolled)
        out = "25863288 ./.venv/bin/mypy\n9871104 ./uv.lock\n812330 ./docs/assets/demo.gif\n204816 ./src/gentui/tui/app.py\n88214 ./README.md\n"
        await driver.push(1, RunStartedEvent(thread_id="t", run_id="r2"),
                          *tool("c2", "run_command", {"approval_id": "c1"}, json.dumps({"command": cmd, "exit_code": 0, "timed_out": False, "truncated": False, "output": out})),
                          *say("a2", "The five largest files are listed above. `mypy` in the virtualenv is the biggest."),
                          RunFinishedEvent(thread_id="t", run_id="r2"), None)
        await shot(2800)

        prompt.value = "chart those sizes"
        await pilot.press("enter")
        spec = {"type": "bar", "title": "Largest files (MB)", "x": ["mypy", "uv.lock", "demo.gif", "app.py", "README"],
                "series": [{"name": "MB", "values": [24.7, 9.4, 0.8, 0.2, 0.1]}], "y_label": "MB"}
        await driver.push(2, RunStartedEvent(thread_id="t", run_id="r3"), *tool("c3", "show_chart", spec, "Chart shown."),
                          *say("a3", "Here's the chart."), RunFinishedEvent(thread_id="t", run_id="r3"), None)
        await shot(3600)

    frames = [to_p(img) for img, _ in shots]
    frames[0].save(OUT / "demo.gif", save_all=True, append_images=frames[1:], duration=[ms for _, ms in shots], loop=0, optimize=True, disposal=2)
    shots[-2][0].save(OUT / "screenshot.png", optimize=True)  # a still for the top of the README
    print("demo.gif", frames[0].size, len(frames), "frames")


if __name__ == "__main__":
    import sys

    which = set(sys.argv[1:]) or {"logo", "hero", "demo"}
    if "logo" in which:
        build_logo()
    if "hero" in which:
        build_hero()
    if "demo" in which:
        asyncio.run(asyncio.wait_for(build_demo(), timeout=120))
