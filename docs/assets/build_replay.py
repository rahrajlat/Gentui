"""Regenerate replay.gif: `gentui --replay` in action (play, pause, seek back and forward, open the chain of thought).

    uv run --with pillow python docs/assets/build_replay.py

A session is recorded from the demo scenes into a temporary file, then played back in the real replay UI. Frames are
captured at chosen moments, so the GIF is deterministic. Captions are drawn on top.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from textual.widgets import Collapsible

from build_agentcore_demo import shell_image
from build_assets import OUT, Config, screen_image, to_p
from build_tour import captioned
from gentui import session
from gentui.tui import demo
from gentui.tui.replay import ReplayApp

SIZE = (100, 38)


async def record(path: Path) -> None:
    app = demo.DemoApp(demo.DemoClient(speed=5), Config(splash=False), "all")
    app.recorder = session.Recorder(path, "demo")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause(0.5)
        while any(w.group == "demo" and not w.is_finished for w in app.workers):
            await pilot.pause(0.2)


def moment(s: session.Session, kind: str, nth: int = 0, **match) -> float:
    """Replay-timeline second of the nth item whose event type (or kind) matches."""
    hits = [i.v for i in s.items if (i.kind == kind if kind != "event" else i.event is not None)
            and all(getattr(i.event, k, None) == v for k, v in match.items())]
    return hits[nth]


async def build() -> None:
    work = Path(tempfile.mkdtemp())
    path = work / "my_session.json"
    await record(path)
    loaded = session.load(path)
    cfg = Config()
    app = ReplayApp(loaded, cfg)
    shots: list[tuple] = []
    caption = {"text": "", "n": 0}

    async with app.run_test(size=SIZE) as pilot:
        async def settle() -> None:
            await pilot.pause(0.15)
            while app._seek is not None:
                await pilot.pause(0.1)
            await pilot.pause(1.0)  # rebuilding the chat after a big jump takes a moment

        async def shot(ms: int, text: str | None = None) -> None:
            if text:
                caption["text"], caption["n"] = text, caption["n"] + 1
            await settle()
            shots.append((captioned(screen_image(app), caption["text"], f"{caption['n']}/8"), ms))

        async def goto(seconds: float) -> None:
            app.seek(seconds)
            await settle()

        d = loaded.duration
        think = moment(loaded, "event", type="REASONING_MESSAGE_CONTENT")
        card = moment(loaded, "resume")  # the approval has just been answered
        before = card - 0.05
        end_of_approval = moment(loaded, "new", 2) - 0.05
        chart_at = moment(loaded, "new", 3) - 0.05  # the last scene ends with a /new: stop just before it

        app.playing = False
        await goto(0)
        await shot(2200, "gentui --replay my_session: no backend needed")
        app.playing = True
        await pilot.pause(0.8)
        await shot(900, "Plays back the streamed chat, thinking included")
        app.playing = False
        await goto(think + 0.3)
        await shot(1800)
        await goto(before)
        await shot(2600, "Tools, plan and approval cards, drawn as they were live")
        await goto(end_of_approval)
        await shot(2600, "...with the decision, the output and the answer")
        await pilot.press("t")
        await shot(3000, "Open or close the chain of thought: press t or click it")
        await pilot.press("t")
        await goto(chart_at)
        await shot(3000, "Tables and charts too. Drag the bar to seek anywhere")
        await goto(before)
        await shot(2400, "Rewind: the chat is rebuilt to that exact moment")
        app.playing = True  # playing, then the space bar pauses it
        await pilot.pause(0.4)
        await pilot.press("space")
        await pilot.press("plus")
        await pilot.press("plus")
        await shot(2600, "Pause with space, speed up with + (0.5x to 8x)")

    size = shots[0][0].size
    cyan, grey, white = (79, 214, 200), (139, 147, 161), (230, 233, 239)
    h = (size[0], size[1] - 66)
    lines = [(grey, "$ gentui http://localhost:8000/agent --record my_session"), (cyan, "Saved the session to my_session.json."),
             (grey, "$ gentui --replay my_session")]
    intro = [(captioned(shell_image(lines[:2], h), "Record any session to JSON, then replay it", "0/8"), 1800),
             (captioned(shell_image(lines, h), "Record any session to JSON, then replay it", "0/8"), 1000)]
    frames_src = intro + shots
    frames = [to_p(img) for img, _ in frames_src]
    out = OUT / "replay.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=[ms for _, ms in frames_src], loop=0, optimize=True, disposal=2)
    print(out, frames[0].size, len(frames), "frames", out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(build(), timeout=240))
