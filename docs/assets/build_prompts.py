"""Regenerate prompts.gif: `gentui --prompts prompts.yml --record baseline` sending a list of prompts by itself.

    uv run --with pillow python docs/assets/build_prompts.py

A scripted agent answers the prompts through the real `--prompts` runner; frames are captured at chosen moments, so the
GIF is deterministic and needs no model. Captions are drawn on top.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_agentcore_demo import shell_image
from build_assets import OUT, Config, screen_image, to_p
from build_compare import PROMPTS, Scripted, v1
from build_tour import captioned
from gentui import session
from gentui.tui.app import GentuiApp

SIZE = (100, 34)
STEPS = 4


async def build() -> None:
    work = Path(tempfile.mkdtemp())
    app = GentuiApp(Scripted(v1), Config(splash=False))
    app.queued_prompts = PROMPTS
    app.recorder = session.Recorder(work / "baseline.json", "demo")
    shots: list[tuple] = []
    cap = {"text": "", "n": 0}

    async with app.run_test(size=SIZE) as pilot:
        async def shot(ms: int, text: str | None = None, wait: float = 0.6) -> None:
            if text:
                cap["text"], cap["n"] = text, cap["n"] + 1
            await pilot.pause(wait)
            shots.append((captioned(screen_image(app), cap["text"], f"{cap['n']}/{STEPS}"), ms))

        await shot(2400, "The first prompt is sent for you", wait=0.5)
        await shot(2600, "The answer finishes, then the next prompt goes out", wait=1.2)
        while any(w.group == "prompts" and not w.is_finished for w in app.workers) or app._busy:
            await pilot.pause(0.2)
        await shot(3200, "Charts, tables and tools render as usual", wait=0.8)
        await shot(3000, "Then the chat stays open: carry on by hand, or /quit", wait=0.5)

    size = shots[0][0].size
    cyan, grey, white = (79, 214, 200), (139, 147, 161), (230, 233, 239)
    h = (size[0], size[1] - 66)
    yml = [(grey, "# prompts.yml"), (cyan, "prompts:"), (white, f"  - {PROMPTS[0]}"), (white, f"  - text: {PROMPTS[1]}"),
           (white, ""), (grey, "$ gentui http://localhost:8000/agent --prompts prompts.yml --record baseline")]
    frames_src = [(captioned(shell_image(yml, h), "Put the messages in a YAML file", f"0/{STEPS}"), 3800)] + shots
    frames = [to_p(img) for img, _ in frames_src]
    out = OUT / "prompts.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=[ms for _, ms in frames_src], loop=0, optimize=True, disposal=2)
    print(out, frames[0].size, len(frames), "frames", out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(build(), timeout=240))
