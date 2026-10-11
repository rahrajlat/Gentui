"""Regenerate judges.gif: the Judge drop-down in `gentui --compare`, scoring each prompt.

    uv run --with pillow python docs/assets/build_judges.py

Reuses the two scripted runs from build_compare.py and a scripted judge, so the GIF is deterministic and needs no model.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_agentcore_demo import shell_image
from build_assets import OUT, Config, screen_image, to_p
from build_compare import SIZE, my_judge, record, v1, v2
from build_tour import captioned
from gentui import plugins, session
from gentui.tui.compare import CompareApp

STEPS = 3


async def build() -> None:
    work = Path(tempfile.mkdtemp())
    await record(work / "v1.json", v1)
    await record(work / "v2.json", v2)
    plugins.register_judge("my_judge")(my_judge)
    app = CompareApp([session.load(work / "v1.json"), session.load(work / "v2.json")], Config())
    shots: list[tuple] = []
    cap = {"text": "", "n": 0}

    async with app.run_test(size=SIZE) as pilot:
        async def shot(ms: int, text: str | None = None, wait: float = 0.8) -> None:
            if text:
                cap["text"], cap["n"] = text, cap["n"] + 1
            await pilot.pause(wait)
            shots.append((captioned(screen_image(app, size=15), cap["text"], f"{cap['n']}/{STEPS}"), ms))

        await shot(2800, "Two runs, no judge yet")
        app.query_one("#pick-judge").value = "my_judge"
        await pilot.pause(0.3)
        await shot(1200, "Pick a judge from the drop-down", wait=0.1)
        await shot(4200, "Each prompt gets a score and a comment on the key difference", wait=1.4)
        app.query_one("#pick-prompt").value = 1
        await pilot.pause(0.3)
        await shot(3600, "Green from 80%, yellow from 50%, red below. The summary shows the average", wait=1.0)

    size = shots[0][0].size
    cyan, grey, white = (79, 214, 200), (139, 147, 161), (230, 233, 239)
    h = (size[0], size[1] - 66)
    lines = [(grey, "$ gentui --compare v1,v2 --judge ollama:gpt-oss:120b-cloud"), (white, ""),
             (grey, "# or write your own"), (cyan, '@register_judge("my_judge")'),
             (white, "async def my_judge(case): ..."), (grey, "$ gentui --compare v1,v2 --plugin my_judge.py --judge my_judge")]
    frames_src = [(captioned(shell_image(lines, h), "Turn on a judge: built in for Ollama, or your own function", f"0/{STEPS}"), 4000)] + shots
    frames = [to_p(img.resize(size) if img.size != size else img) for img, _ in frames_src]
    out = OUT / "judges.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=[ms for _, ms in frames_src], loop=0, optimize=True, disposal=2)
    print(out, frames[0].size, len(frames), "frames", out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(build(), timeout=240))
