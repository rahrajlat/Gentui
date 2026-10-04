"""Config, plugins, slash commands, auth headers and reasoning in the TUI."""

import json

import httpx
import pytest
from ag_ui.core import (
    ReasoningEndEvent, ReasoningMessageContentEvent, ReasoningMessageEndEvent,
    ReasoningMessageStartEvent, ReasoningStartEvent, RunFinishedEvent, RunStartedEvent,
    ToolCallArgsEvent, ToolCallEndEvent, ToolCallResultEvent, ToolCallStartEvent,
)
from textual.widgets import Collapsible, Static

from gentui import plugins
from gentui.cli import main as cli_main, parse_headers
from gentui.config import Config, load_config
from gentui.tui.agui_client import AguiClient
from gentui.tui.app import GentuiApp
from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import widget_for


class ScriptClient:
    def __init__(self, *events):
        self.events = events
        self.calls = []

    async def run(self, thread_id, text, forwarded_props=None):
        self.calls.append((text, forwarded_props))
        for ev in self.events:
            yield ev


# -- config -------------------------------------------------------------------------------


def test_config_file_env_and_flags_priority(tmp_path, monkeypatch):
    (tmp_path / "gentui.toml").write_text('url = "http://file/agent"\ntitle = "Mine"\ntoken = "t1"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GENTUI_URL", raising=False)
    monkeypatch.delenv("GENTUI_TOKEN", raising=False)

    cfg = load_config()
    assert (cfg.url, cfg.title, cfg.token) == ("http://file/agent", "Mine", "t1")

    monkeypatch.setenv("GENTUI_URL", "http://env/agent")
    assert load_config().url == "http://env/agent"
    assert load_config(url="http://flag/agent").url == "http://flag/agent"
    assert load_config(url=None).url == "http://env/agent"  # None = flag not given


def test_config_rejects_unknown_option_and_resolves_css(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("colour = 'red'\n")
    with pytest.raises(ValueError, match="colour"):
        load_config(str(bad))

    good = tmp_path / "ok.toml"
    good.write_text('css = "theme.tcss"\n')
    assert load_config(str(good)).css == str(tmp_path / "theme.tcss")


def test_token_becomes_bearer_header_without_overriding_explicit_one():
    assert Config(token="abc").request_headers == {"Authorization": "Bearer abc"}
    assert Config(token="abc", headers={"Authorization": "Basic x"}).request_headers == {"Authorization": "Basic x"}


def test_cli_parses_headers_and_rejects_garbage():
    assert parse_headers(["X-A: 1", "X-B:2"]) == {"X-A": "1", "X-B": "2"}
    with pytest.raises(SystemExit):
        parse_headers(["nonsense"])


def test_cli_reports_missing_config(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["--config", "/nonexistent/gentui.toml"])
    assert "config file not found" in str(exc.value)


async def test_client_sends_custom_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, content=b"")

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    httpx.AsyncClient = lambda **kw: real(transport=transport, **kw)  # type: ignore[assignment]
    try:
        client = AguiClient("http://x/agent", {"Authorization": "Bearer abc"})
        assert [e async for e in client.run("t", "hi")] == []
    finally:
        httpx.AsyncClient = real  # type: ignore[assignment]
    assert seen["authorization"] == "Bearer abc" and seen["accept"] == "text/event-stream"


# -- app: look & feel, slash commands -------------------------------------------------------


async def test_title_welcome_placeholder_and_theme_come_from_config():
    cfg = Config(title="Acme", subtitle="ops", welcome="hi {url}", placeholder="type…", theme="nord")
    app = GentuiApp(ScriptClient(), cfg)
    async with app.run_test() as pilot:
        assert app.title == "Acme" and app.sub_title == "ops" and app.theme == "nord"
        assert "hi http://localhost:8000/agent" in str(app.query_one("#welcome", Static).render())
        assert app.query_one("#prompt").placeholder == "type…"


async def test_builtin_slash_commands():
    client = ScriptClient()
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"/theme nord", "enter")
        await pilot.pause()
        assert app.theme == "nord"

        thread = app.thread_id
        await pilot.press(*"/clear", "enter")
        await pilot.pause()
        assert app.thread_id != thread and not app.query(".user")

        await pilot.press(*"/reasoning", "enter")
        await pilot.pause()
        assert app.show_reasoning is False
        assert client.calls == []  # commands never reach the agent


async def test_unknown_slash_text_goes_to_the_agent():
    client = ScriptClient(RunStartedEvent(thread_id="t", run_id="r"), RunFinishedEvent(thread_id="t", run_id="r"))
    app = GentuiApp(client)
    async with app.run_test() as pilot:
        await pilot.press(*"/etc/hosts?", "enter")
        await pilot.pause(0.3)
    assert client.calls[0][0] == "/etc/hosts?"


async def test_forwarded_props_are_sent_with_every_run():
    client = ScriptClient()
    app = GentuiApp(client, Config(forwarded_props={"model": "fast"}))
    async with app.run_test() as pilot:
        await pilot.press(*"hi", "enter")
        await pilot.pause(0.3)
    assert client.calls == [("hi", {"model": "fast"})]


# -- reasoning ------------------------------------------------------------------------------


def reasoning_run():
    yield RunStartedEvent(thread_id="t", run_id="r")
    yield ReasoningStartEvent(message_id="r1")
    yield ReasoningMessageStartEvent(message_id="r1", role="reasoning")
    yield ReasoningMessageContentEvent(message_id="r1", delta="let me ")
    yield ReasoningMessageContentEvent(message_id="r1", delta="think")
    yield ReasoningMessageEndEvent(message_id="r1")
    yield ReasoningEndEvent(message_id="r1")
    yield RunFinishedEvent(thread_id="t", run_id="r")


async def test_reasoning_renders_as_collapsed_thought_block():
    app = GentuiApp(ScriptClient(*reasoning_run()))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"q", "enter")
        await pilot.pause(0.5)
        box = app.query_one(Collapsible)
        assert box.title == "Thought" and box.collapsed
        assert "let me think" in str(box.query_one(".thinking", Static).render())


async def test_reasoning_can_be_turned_off():
    app = GentuiApp(ScriptClient(*reasoning_run()), Config(show_reasoning=False))
    async with app.run_test() as pilot:
        await pilot.press(*"q", "enter")
        await pilot.pause(0.5)
        assert not app.query(Collapsible)


# -- plugins --------------------------------------------------------------------------------

PLUGIN = '''
from gentui.plugins import on_event, register_command
from gentui.tui.widgets.base import ToolWidget
from gentui.tui.widgets.registry import register_widget

SEEN = []

@register_widget("fancy_tool")
class Fancy(ToolWidget):
    def on_end(self, args):
        super().on_end(args)
        self.show("FANCY " + args["x"])

@register_command("ping", "say pong")
def ping(app, args):
    app.notify("pong " + args)
    SEEN.append(("cmd", args))

@on_event("TOOL_CALL_END")
def seen(app, event):
    SEEN.append(("event", event.tool_call_id))

def setup(app):
    SEEN.append(("setup", app.config.title))
'''


@pytest.fixture
def clean_plugins():
    commands, hooks, setups = dict(plugins.COMMANDS), list(plugins.HOOKS), list(plugins.SETUPS)
    yield
    plugins.COMMANDS.clear(); plugins.COMMANDS.update(commands)
    plugins.HOOKS[:] = hooks
    plugins.SETUPS[:] = setups


async def test_plugin_file_adds_widget_command_hook_and_setup(tmp_path, clean_plugins):
    path = tmp_path / "myplug_a.py"
    path.write_text(PLUGIN)
    run = [
        RunStartedEvent(thread_id="t", run_id="r"),
        ToolCallStartEvent(tool_call_id="c1", tool_call_name="fancy_tool"),
        ToolCallArgsEvent(tool_call_id="c1", delta=json.dumps({"x": "yes"})),
        ToolCallEndEvent(tool_call_id="c1"),
        RunFinishedEvent(thread_id="t", run_id="r"),
    ]
    app = GentuiApp(ScriptClient(*run), Config(title="T", plugins=[str(path)]))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.5)
        fancy = [w for w in app.query(ToolWidget) if w.tool_name == "fancy_tool"][0]
        assert "FANCY yes" in str(fancy.query_one("#body", Static).render())

        await pilot.press(*"/ping hello", "enter")
        await pilot.pause(0.2)

    seen = plugins.sys.modules["gentui_plugin_myplug_a"].SEEN
    assert ("setup", "T") in seen and ("event", "c1") in seen and ("cmd", "hello") in seen


async def test_broken_plugin_is_reported_not_fatal(tmp_path, clean_plugins):
    bad = tmp_path / "myplug_b.py"
    bad.write_text("raise RuntimeError('boom')")
    app = GentuiApp(ScriptClient(), Config(plugins=[str(bad)]))
    assert any("boom" in e for e in app._plugin_errors)
    async with app.run_test() as pilot:  # the app still starts
        await pilot.pause()


async def test_failing_hook_does_not_break_the_run(clean_plugins):
    @plugins.on_event("RUN_STARTED")
    def broken(app, event):
        raise ValueError("nope")

    run = [RunStartedEvent(thread_id="t", run_id="r"), *reasoning_run()]
    app = GentuiApp(ScriptClient(*run))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"q", "enter")
        await pilot.pause(0.5)
        assert app.query(Collapsible)  # later events were still handled


def test_config_widget_mapping_and_default_widget(tmp_path, monkeypatch, clean_plugins):
    mod = tmp_path / "mywidgets_c.py"
    mod.write_text(
        "from gentui.tui.widgets.base import ToolWidget\n"
        "class A(ToolWidget): pass\nclass B(ToolWidget): pass\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    from gentui.tui.widgets import registry

    old = dict(registry._WIDGETS), registry._default
    try:
        errors = plugins.load_all([], {"mapped_tool": "mywidgets_c:A"}, "mywidgets_c:B")
        assert errors == []
        assert type(widget_for("1", "mapped_tool")).__name__ == "A"
        assert type(widget_for("2", "anything_else")).__name__ == "B"
    finally:
        registry._WIDGETS.clear(); registry._WIDGETS.update(old[0]); registry._default = old[1]


async def test_dev_pane_shows_raw_backend_payloads():
    raw = '{"type":"RUN_STARTED","threadId":"t","runId":"r","extra":{"kept":"as sent"}}'
    sse = f"data: {raw}\n\n".encode()
    real = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=sse))
    httpx.AsyncClient = lambda **kw: real(transport=transport, **kw)  # type: ignore[assignment]
    try:
        app = GentuiApp(AguiClient("http://x/agent"), Config(dev_pane=True))
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press(*"hi", "enter")
            await pilot.pause(0.5)
            logged = [strip.text for strip in app.query_one("#events").lines]
    finally:
        httpx.AsyncClient = real  # type: ignore[assignment]
    assert any(raw in line or '"extra":{"kept":"as sent"}' in line for line in logged), logged
    assert not app.query("#state")


async def test_search_memory_renders_as_quiet_one_liner():
    run = [
        RunStartedEvent(thread_id="t", run_id="r"),
        ToolCallStartEvent(tool_call_id="m1", tool_call_name="search_memory"),
        ToolCallArgsEvent(tool_call_id="m1", delta=json.dumps({"query": "editor"})),
        ToolCallEndEvent(tool_call_id="m1"),
        ToolCallResultEvent(message_id="x", tool_call_id="m1", content="User's favorite editor is Neovim", role="tool"),
        RunFinishedEvent(thread_id="t", run_id="r"),
    ]
    app = GentuiApp(ScriptClient(*run))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(*"q", "enter")
        await pilot.pause(0.5)
        w = [w for w in app.query(ToolWidget) if w.tool_name == "search_memory"][0]
        assert "recalled “editor”" in str(w.query_one("#body", Static).render())



# -- charts ---------------------------------------------------------------------------------


def chart_run(spec):
    return [
        RunStartedEvent(thread_id="t", run_id="r"),
        ToolCallStartEvent(tool_call_id="ch", tool_call_name="show_chart"),
        ToolCallArgsEvent(tool_call_id="ch", delta=json.dumps(spec)),
        ToolCallEndEvent(tool_call_id="ch"),
        RunFinishedEvent(thread_id="t", run_id="r"),
    ]


@pytest.mark.parametrize("spec", [
    {"type": "line", "title": "T", "x": [1, 2, 3], "series": [{"name": "a", "values": [1, 4, 9]}]},
    {"type": "line", "x": ["Mon", "Tue"], "series": [{"name": "a", "values": [1, 2]}, {"name": "b", "values": [2, 1]}]},
    {"type": "bar", "x": ["a", "b", "c"], "series": [{"name": "n", "values": [3, 1, 2]}]},
    {"type": "bar", "x": ["a", "b"], "series": [{"name": "p", "values": [1, 2]}, {"name": "q", "values": [2, 3]}]},
    {"type": "scatter", "x": [1, 2, 3], "series": [{"name": "s", "values": [3, 1, 2]}]},
    {"type": "histogram", "bins": 4, "series": [{"name": "h", "values": [1, 2, 2, 3, 3, 3, 4]}]},
])
async def test_chart_types_render(spec):
    from textual_plotext import PlotextPlot

    app = GentuiApp(ScriptClient(*chart_run(spec)))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"c", "enter")
        await pilot.pause(0.5)
        plot = app.query_one(PlotextPlot)
        assert plot.display, [str(s.render()) for s in app.query("#body")]


@pytest.mark.parametrize("spec,message", [
    ({"type": "pie", "series": [{"values": [1]}]}, "unknown chart type"),
    ({"type": "line", "series": []}, "series is empty"),
    ({"type": "line", "x": [1, 2], "series": [{"name": "a", "values": [1]}]}, "1 values for 2 x points"),
    ({"type": "bar", "x": ["a"], "series": [{"name": "a", "values": ["many"]}]}, "must be numbers"),
])
async def test_bad_chart_spec_shows_message_not_crash(spec, message):
    from textual_plotext import PlotextPlot

    app = GentuiApp(ScriptClient(*chart_run(spec)))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"c", "enter")
        await pilot.pause(0.5)
        assert not app.query_one(PlotextPlot).display
        assert any(message in str(s.render()) for s in app.query("#body"))
