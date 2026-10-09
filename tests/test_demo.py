"""`gentui --demo`: the scripted tour plays through, with a choice of scene."""

import asyncio
import io

import pytest
from textual.widgets import Static

from gentui.cli import main
from gentui.config import Config
from gentui.tui import demo


async def play(scene: str, timeout: float = 60) -> demo.DemoApp:
    app = demo.DemoApp(demo.DemoClient(speed=60), Config(splash=False), scene)
    async with app.run_test(size=(100, 40)) as pilot:
        await asyncio.wait_for(_finished(app, pilot), timeout)
    return app


async def _finished(app, pilot) -> None:
    await pilot.pause(0.5)
    while any(w.group == "demo" and not w.is_finished for w in app.workers):
        await pilot.pause(0.1)


@pytest.mark.parametrize("scene", ["chat", "approval", "widgets", "devtools"])
async def test_every_scene_plays_to_the_end(scene):
    app = await play(scene)
    assert not app._busy and not app._outbox


async def test_approval_scene_runs_the_approved_command():
    app = demo.DemoApp(demo.DemoClient(speed=60), Config(splash=False), "approval")
    async with app.run_test(size=(100, 40)) as pilot:
        await asyncio.wait_for(_finished(app, pilot), 60)
        text = "\n".join(str(w.render()) for w in app.query(Static))
        assert "3.12.4" in text and "exit 0" in text
        assert [e["status"] for e in app.state["plan"]] == ["completed"] * 3


async def test_the_whole_movie_plays():
    app = await play("all", timeout=120)
    assert not app._busy


async def test_demo_command_lists_and_switches_scenes():
    app = demo.DemoApp(demo.DemoClient(speed=60), Config(splash=False), "devtools")
    async with app.run_test(size=(100, 40)) as pilot:
        await asyncio.wait_for(_finished(app, pilot), 60)
        await demo.demo(app, "")
        await pilot.pause()
        assert any("approval" in str(w.render()) for w in app.query(Static))
        await demo.demo(app, "widgets")
        await asyncio.wait_for(_finished(app, pilot), 60)
        assert not app._busy


async def test_free_typing_after_the_demo_gets_the_fallback_reply():
    app = demo.DemoApp(demo.DemoClient(speed=60), Config(splash=False), "chat")
    async with app.run_test(size=(100, 40)) as pilot:
        await asyncio.wait_for(_finished(app, pilot), 60)
        app.send("hello")
        await pilot.pause(1.5)
        assert not app._busy


class Tty(io.StringIO):
    def isatty(self):
        return True


def test_menu_takes_a_number_a_name_or_enter(monkeypatch):
    for answer, expected in (("3", "approval"), ("widgets", "widgets"), ("", "all"), ("9\nchat", "chat")):
        answers = iter(answer.split("\n"))
        monkeypatch.setattr("builtins.input", lambda _="", a=answers: next(a))
        assert demo.choose_scene(Tty(), out=lambda *_: None) == expected


def test_menu_without_a_terminal_plays_everything():
    assert demo.choose_scene(io.StringIO()) == "all"


def test_cli_rejects_an_unknown_scene(capsys):
    with pytest.raises(SystemExit):
        main(["--demo", "nope"])
    assert "unknown demo scene" in capsys.readouterr().err
