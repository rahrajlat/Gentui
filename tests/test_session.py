"""--record and --replay: the JSON file, and the replay player."""

import asyncio
import json
from pathlib import Path

import pytest
from textual.widgets import Button, Collapsible, Static

from gentui import session
from gentui.cli import main
from gentui.config import Config
from gentui.tui import demo
from gentui.tui.replay import ReplayApp, Scrubber
from gentui.tui.widgets.chart import ChartWidget
from gentui.tui.widgets.command import CommandWidget
from gentui.tui.widgets.plan import PlanWidget
from gentui.tui.widgets.table import TableWidget


async def record(path: Path, scene: str = "all") -> None:
    app = demo.DemoApp(demo.DemoClient(speed=60), Config(splash=False), scene)
    app.recorder = session.Recorder(path, "demo")
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.5)
        while any(w.group == "demo" and not w.is_finished for w in app.workers):
            await pilot.pause(0.1)
    assert path.exists()


@pytest.fixture
async def approval(tmp_path):
    path = tmp_path / "s.json"
    await record(path, "approval")
    return path


def replay_app(path: Path) -> ReplayApp:
    return ReplayApp(session.load(path), Config())


async def at_end(app, pilot) -> None:
    for _ in range(200):
        await pilot.pause(0.1)
        if app._index >= len(app.session.items):
            return
    raise AssertionError("the replay never reached the end")


def texts(app) -> str:
    return "\n".join(str(w.render()) for w in app.query(Static))


# -- the file -----------------------------------------------------------------------------------


def test_names_get_a_json_extension():
    assert session.resolve("demo") == Path("demo.json")
    assert session.resolve("a/b/demo.json") == Path("a/b/demo.json")


async def test_recording_has_the_messages_and_the_events(approval):
    doc = json.loads(approval.read_text())
    assert doc["format"] == "gentui-session" and doc["version"] == 1
    kinds = [i["kind"] for i in doc["items"]]
    assert kinds.count("user") == 1 and kinds.count("resume") == 1
    types = {i["event"]["type"] for i in doc["items"] if i["kind"] == "event"}
    assert {"TEXT_MESSAGE_CONTENT", "REASONING_MESSAGE_CONTENT", "TOOL_CALL_ARGS", "STATE_SNAPSHOT", "RUN_FINISHED"} <= types
    assert [i["t"] for i in doc["items"]] == sorted(i["t"] for i in doc["items"])
    assert "token" not in approval.read_text().lower()


def test_an_existing_recording_is_never_overwritten(tmp_path):
    (tmp_path / "s.json").write_text("{}")
    with pytest.raises(session.SessionError, match="already exists"):
        session.Recorder(tmp_path / "s.json")
    assert (tmp_path / "s.json").read_text() == "{}"


def test_long_waits_are_squeezed_on_the_replay_timeline(tmp_path):
    path = tmp_path / "s.json"
    rec = session.Recorder(path)
    rec._t0 -= 100  # pretend 100 s passed before the first message
    rec.user("hi")
    rec._t0 -= 100
    rec.user("again")
    rec.save()
    loaded = session.load(path)
    assert [i.v for i in loaded.items] == [0.0, session.IDLE_CAP]
    assert loaded.items[1].t > 100


@pytest.mark.parametrize("content, message", [
    ("nope", "not valid JSON"),
    ('{"format": "other"}', "not a Gentui session"),
    ('{"format": "gentui-session", "version": 9}', "version 9"),
    ('{"format": "gentui-session", "version": 1, "items": [{"t": 0, "kind": "event", "event": {"type": "X"}}]}', "item 1"),
])
def test_bad_files_get_a_clear_error(tmp_path, content, message):
    path = tmp_path / "s.json"
    path.write_text(content)
    with pytest.raises(session.SessionError, match=message):
        session.load(path)


def test_cli_flags(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--replay", "missing"])
    assert "cannot read" in str(exc.value)
    with pytest.raises(SystemExit):
        main(["--record", "a", "--replay", "b"])
    assert "cannot be used together" in capsys.readouterr().err


# -- the replay ---------------------------------------------------------------------------------


async def test_replay_shows_tools_plan_approval_and_thinking(approval):
    app = replay_app(approval)
    async with app.run_test(size=(100, 40)) as pilot:
        app.speed = 8
        await at_end(app, pilot)
        card = app.query_one(CommandWidget)
        assert card.state == "approved"
        assert all(b.disabled for b in card.query(Button))  # a replay cannot be answered
        assert "3.12.4" in texts(app) and "recalled" in texts(app)
        assert [e["status"] for e in app.state["plan"]] == ["completed"] * 3
        assert app.query_one(PlanWidget)
        thought = app.query_one(Collapsible)
        assert thought.collapsed and "Thought for" in str(thought.title)


async def test_replay_shows_tables_and_charts(tmp_path):
    path = tmp_path / "w.json"
    await record(path, "widgets")
    app = replay_app(path)
    async with app.run_test(size=(100, 40)) as pilot:
        app.speed = 8
        await at_end(app, pilot)
        assert app.query(TableWidget) and app.query(ChartWidget)


async def test_thoughts_can_be_opened_and_closed_while_replaying(approval):
    app = replay_app(approval)
    async with app.run_test(size=(100, 40)) as pilot:
        app.speed = 8
        await at_end(app, pilot)
        thought = app.query_one(Collapsible)
        await pilot.press("t")
        assert not thought.collapsed
        await pilot.press("t")
        assert thought.collapsed
        thought.collapsed = False  # clicking the title does the same
        assert not thought.collapsed


async def test_pause_play_and_the_space_bar(approval):
    app = replay_app(approval)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("space")
        assert not app.playing
        frozen = app.pos
        await pilot.pause(0.5)
        assert app.pos == frozen
        assert str(app.query_one("#playpause", Button).label) == "▶ Play"
        await pilot.press("space")
        assert app.playing


async def test_seeking_backwards_rebuilds_the_chat(approval):
    app = replay_app(approval)
    async with app.run_test(size=(100, 40)) as pilot:
        app.speed = 8
        await at_end(app, pilot)
        assert app.query(CommandWidget)
        app.playing = False
        app.seek(0.0)
        await pilot.pause(0.4)
        assert not app.query(CommandWidget) and not app.query(Collapsible)
        assert app.pos == 0.0
        app.seek(app.session.duration)  # forwards again, all the way
        await pilot.pause(0.6)
        assert app.query_one(CommandWidget).state == "approved"
        mid = app.session.duration / 2
        app.seek(mid)  # back to the middle: the card is there but its answer has not happened yet
        await pilot.pause(0.6)
        assert app.pos == pytest.approx(mid)
        assert all(i.v <= mid + 1e-9 for i in app.session.items[: app._index])


async def test_the_slider_seeks_and_the_keys_skip(approval):
    app = replay_app(approval)
    async with app.run_test(size=(100, 40)) as pilot:
        app.playing = False
        await pilot.press("right")
        await pilot.pause(0.3)
        assert app.pos == pytest.approx(min(5.0, app.session.duration))
        scrubber = app.query_one(Scrubber)
        scrubber.post_message(Scrubber.Seek(1.0))
        await pilot.pause(0.5)
        assert app.pos == pytest.approx(app.session.duration)
        await pilot.press("home")
        await pilot.pause(0.4)
        assert app.pos == 0.0
        await pilot.press("plus")
        assert app.speed == 2.0


async def test_an_empty_recording_opens(tmp_path):
    path = tmp_path / "e.json"
    session.Recorder(path).save()
    app = replay_app(path)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("space")
        await pilot.pause(0.2)
