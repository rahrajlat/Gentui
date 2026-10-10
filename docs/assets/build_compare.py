"""Regenerate compare.gif: `gentui --compare` with a judge (two sessions diffed side by side, a score and comment per prompt).

    uv run --with pillow python docs/assets/build_compare.py

Two sessions are recorded from scripted agents (v1 and v2) that answer the same two prompts differently, using the real
`--prompts` runner. They are then opened in the real compare UI with a scripted judge, so the GIF is deterministic and
needs no model. Captions are drawn on top.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from build_agentcore_demo import shell_image
from build_assets import OUT, Config, screen_image, to_p
from build_tour import captioned
from gentui import plugins, session
from gentui.tui.app import GentuiApp
from gentui.tui.compare import CompareApp
from gentui.tui.demo import run, say, think, tool

SIZE = (150, 44)
MOUNTS = ["/var/lib/docker", "/", "/home", "/boot"]
PROMPTS = ["How full is the disk?", "Plot the usage per mount as a chart"]
STEPS = 6


def v1(n: int):
    if n == 0:
        return run(1, think("Check the root disk and compare it with the 85% threshold."),
                   tool("t1", "show_table", {"title": "Disk usage", "columns": ["Mount", "Used %"],
                                             "rows": [["/", "78%"], ["/home", "64%"]]}, "ok"),
                   say("a1", "The root disk is **78% full**: healthy, under your 85% threshold."))
    return run(2, tool("c1", "show_chart", {"type": "bar", "title": "Used % per mount", "x": MOUNTS,
                                            "series": [{"name": "Used %", "values": [91, 78, 64, 22]}], "y_label": "%"}, "ok"),
               say("a2", "`/var/lib/docker` is the busiest mount at **91%**."))


def v2(n: int):
    if n == 0:
        return run(1, think("Check the root disk. Report it plainly."),
                   tool("t1", "show_table", {"title": "Disk usage", "columns": ["Mount", "Used %"],
                                             "rows": [["/", "98%"], ["/home", "64%"]]}, "ok"),
                   say("a1", "The root disk is **98% full**: critical, free some space soon."))
    return run(2, tool("c1", "show_chart", {"type": "bar", "title": "Used % per mount", "x": MOUNTS,
                                            "series": [{"name": "Used %", "values": [91, 98, 64, 22]}], "y_label": "%"}, "ok"),
               say("a2", "`/var/lib/docker` is the busiest mount at **91%**."))


class Scripted:
    def __init__(self, script) -> None:
        self.script, self.calls = script, 0

    async def run(self, thread_id, text, forwarded_props=None, resume=None):
        turn, self.calls = self.script(self.calls), self.calls + 1
        for event in turn:
            yield event


async def record(path: Path, script) -> None:
    app = GentuiApp(Scripted(script), Config(splash=False))
    app.queued_prompts = PROMPTS
    app.recorder = session.Recorder(path, "demo")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.5)
        while app.workers and any(w.group == "prompts" and not w.is_finished for w in app.workers) or app._busy:
            await pilot.pause(0.2)
        await pilot.pause(0.3)


VERDICTS = {
    PROMPTS[0]: (0.22, "Opposite conclusions: A says the root disk is healthy at 78%, B says critical at 98%."),
    PROMPTS[1]: (0.86, "Same chart and finding; only the bar for / differs (78 vs 98)."),
}


async def my_judge(case):  # stands in for a model: the same signature a real judge has
    await asyncio.sleep(0.4)
    score, reason = VERDICTS[case.prompt]
    return {"score": score, "reason": reason}


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

        async def pick(select: str, value) -> None:
            app.query_one(select).value = value
            await pilot.pause(0.3)

        await shot(3000, "Two recorded runs, side by side, as a diff")
        await pick("#pick-prompt", 1)
        await shot(3000, "Pick one prompt from the file: green and red mark what differs")
        await pick("#pick-judge", "my_judge")
        await shot(1200, "Turn on a judge", wait=0.1)
        await shot(3600, "A score and a comment for each prompt, on top", wait=1.2)
        await pick("#pick-prompt", 2)
        await shot(3400, "Charts, tables and tool calls are drawn in full", wait=0.8)
        await pick("#pick-prompt", 0)
        await shot(3400, "All prompts at once, with the judge's average. Pick any two runs", wait=0.6)

    size = shots[0][0].size
    cyan, grey, white = (79, 214, 200), (139, 147, 161), (230, 233, 239)
    h = (size[0], size[1] - 66)
    rec = [(grey, "$ gentui URL --prompts prompts.yml --record v1"), (grey, "$ gentui URL --prompts prompts.yml --record v2")]
    plugin = [(grey, "# my_judge.py"), (white, "from gentui.plugins import register_judge"), (white, ""),
              (cyan, '@register_judge("my_judge")'), (white, "async def my_judge(case):"),
              (white, "    # case.prompt, case.left, case.right, case.left_tools, ..."),
              (white, '    return {"score": 0.8, "reason": "same facts"}'),
              (white, ""), (grey, "$ gentui --compare v1,v2 --plugin my_judge.py --judge my_judge")]
    intro = [(captioned(shell_image(rec, h), "Run the same prompts against two versions of your agent", f"0/{STEPS}"), 3000),
             (captioned(shell_image(plugin, h), "Bring your own judge: one function that returns a score and a reason", f"0/{STEPS}"), 4200)]
    frames_src = intro + shots
    frames = [to_p(img.resize(shots[0][0].size) if img.size != shots[0][0].size else img) for img, _ in frames_src]
    out = OUT / "compare.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=[ms for _, ms in frames_src], loop=0, optimize=True, disposal=2)
    print(out, frames[0].size, len(frames), "frames", out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(build(), timeout=240))
