"""--compare: the diff of two recorded sessions, and the side-by-side view."""

from pathlib import Path

import pytest
from textual.widgets import Select, Static

from gentui import session
from gentui.config import Config
from gentui.tui import demo
from gentui.tui.compare import CompareApp, Block, align, blocks_of, word_diff
from tests.test_session import record


def tool(name: str, args: str = "{}", result: str = "ok") -> Block:
    return Block("tool", name=name, args=args, result=result)


def test_identical_blocks_are_the_same_even_if_the_json_is_spaced_differently():
    a = [Block("user", "hi"), tool("show_table", '{"a": 1, "b": 2}')]
    b = [Block("user", "hi"), tool("show_table", '{"b":2,"a":1}')]
    assert [p.status for p in align(a, b)] == ["same", "same"]


def test_changed_added_and_removed_blocks():
    a = [Block("user", "hi"), Block("text", "one"), tool("ls")]
    b = [Block("user", "hi"), Block("text", "two"), tool("ls"), tool("plot")]
    pairs = align(a, b)
    assert [p.status for p in pairs] == ["same", "changed", "same", "added"]
    assert pairs[2].left.name == pairs[2].right.name == "ls"


def test_a_tool_call_is_only_paired_with_the_same_tool():
    pairs = align([tool("ls")], [tool("plot")])
    assert [p.status for p in pairs] == ["removed", "added"]


def test_reasoning_never_counts_as_a_difference():
    assert align([Block("reasoning", "a")], [Block("reasoning", "b")])[0].status == "same"


def test_word_diff_marks_only_the_words_that_differ():
    left, right = word_diff("the quick fox", "the slow fox")
    assert left.plain == "the quick fox" and right.plain == "the slow fox"
    assert [left.plain[s.start:s.end] for s in left.spans] == ["quick"]
    assert [right.plain[s.start:s.end] for s in right.spans] == ["slow"]


async def test_blocks_come_from_a_recording(tmp_path: Path):
    path = tmp_path / "a.json"
    await record(path, "all")
    blocks, owner = blocks_of(session.load(path))
    kinds = {b.kind for b in blocks}
    assert {"user", "text", "tool"} <= kinds
    assert all(b.name for b in blocks if b.kind == "tool")
    assert owner


async def test_compare_view_draws_both_sides_and_switches(tmp_path: Path):
    await record(tmp_path / "a.json", "chat")
    await record(tmp_path / "b.json", "approval")
    sessions = [session.load(tmp_path / "a.json"), session.load(tmp_path / "b.json")]
    app = CompareApp(sessions, Config())
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.5)
        assert len(app.query(".pair")) > 0
        assert app.query(".cell.changed") and app.query(".cell.added")
        summary = str(app.query_one("#summary", Static).render())
        assert "changed" in summary and "only in b" in summary
        left = app.query_one("#pick-left", Select)
        left.value = 1  # both sides now show b: nothing differs
        await pilot.pause(0.8)
        assert app.picked == [1, 1]
        assert not app.query(".cell.removed") and not app.query(".cell.added") and not app.query(".cell.changed")
        await pilot.press("m")
        assert not app.query_one("#chat").has_class("-words")


async def test_one_prompt_can_be_picked_from_the_drop_down(tmp_path: Path):
    await record(tmp_path / "a.json", "all")
    app = CompareApp([session.load(tmp_path / "a.json")] * 2, Config())
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.5)
        picker = app.query_one("#pick-prompt", Select)
        prompts = len([b for b in blocks_of(app.sessions[0])[0] if b.kind == "user"])
        assert prompts > 1 and len(picker._options) == prompts + 1  # all, then each prompt
        picker.value = 2
        await pilot.pause(0.3)
        shown = [r for r in app.query(".pair") if r.display]
        assert shown and all(r.has_class("turn-2") for r in shown)
        picker.value = 0
        await pilot.pause(0.3)
        assert all(r.display for r in app.query(".pair"))
