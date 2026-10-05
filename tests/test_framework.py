"""Config, plugins, slash commands, auth headers and reasoning in the TUI."""

import json

import httpx
import pytest
from ag_ui.core import (
    TextMessageContentEvent, TextMessageEndEvent, TextMessageStartEvent,
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
        assert box.title.startswith("◈ Thought for") and box.collapsed
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


# -- AG-UI interrupts (approval) --------------------------------------------------------------


def interrupt_finish(*interrupts):
    from ag_ui.core import Interrupt, RunFinishedInterruptOutcome

    return RunFinishedEvent(
        thread_id="t", run_id="r",
        outcome=RunFinishedInterruptOutcome(interrupts=[Interrupt(**i) for i in interrupts]),
    )


def proposal_run(command="ls -la", *extra_interrupts):
    yield RunStartedEvent(thread_id="t", run_id="r")
    yield ToolCallStartEvent(tool_call_id="c1", tool_call_name="propose_command")
    yield ToolCallArgsEvent(tool_call_id="c1", delta=json.dumps(
        {"command": command, "explanation": "list", "risk": "safe"}))
    yield ToolCallEndEvent(tool_call_id="c1")
    yield interrupt_finish(
        {"id": "int-1", "reason": "tool_call", "tool_call_id": "c1", "message": "Run it?"}, *extra_interrupts)


class ResumeClient:
    """Run 1 replays `first`; later runs replay `later`. Records (text, props, resume)."""

    def __init__(self, first, later=()):
        self.first, self.later, self.calls = first, later, []

    async def run(self, thread_id, text, forwarded_props=None, resume=None):
        self.calls.append((text, forwarded_props, resume))
        for ev in (self.first if len(self.calls) == 1 else self.later):
            yield ev


async def test_approve_sends_resume_not_a_fake_message():
    client = ResumeClient(proposal_run(), [RunStartedEvent(thread_id="t", run_id="r2"), RunFinishedEvent(thread_id="t", run_id="r2")])
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.5)
        await pilot.click("#approve")
        await pilot.pause(0.5)
    text, props, resume = client.calls[1]
    assert resume == [{"interruptId": "int-1", "status": "resolved", "payload": {"approved": True}}]
    assert not props  # no out-of-band forwardedProps hack


async def test_edited_command_travels_in_the_resume_payload():
    client = ResumeClient(proposal_run(), [RunStartedEvent(thread_id="t", run_id="r2"), RunFinishedEvent(thread_id="t", run_id="r2")])
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.5)
        await pilot.click("#edit")
        await pilot.pause()
        editor = app.query_one("#editor")
        editor.value = "ls -l"
        await pilot.click("#approve")
        await pilot.pause(0.5)
    assert client.calls[1][2] == [
        {"interruptId": "int-1", "status": "resolved", "payload": {"approved": True, "command": "ls -l"}}]


async def test_reject_cancels_the_interrupt():
    client = ResumeClient(proposal_run(), [RunStartedEvent(thread_id="t", run_id="r2"), RunFinishedEvent(thread_id="t", run_id="r2")])
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.5)
        await pilot.click("#reject")
        await pilot.pause(0.5)
    assert client.calls[1][2] == [{"interruptId": "int-1", "status": "cancelled"}]


async def test_unclaimed_interrupt_gets_a_generic_prompt_and_all_must_be_answered():
    from gentui.tui.widgets.interrupt import InterruptWidget

    run = [
        RunStartedEvent(thread_id="t", run_id="r"),
        interrupt_finish(
            {"id": "a", "reason": "confirmation", "message": "Deploy to prod?"},
            {"id": "b", "reason": "confirmation", "message": "Also restart?"},
        ),
    ]
    client = ResumeClient(run, [RunStartedEvent(thread_id="t", run_id="r2"), RunFinishedEvent(thread_id="t", run_id="r2")])
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.5)
        first, second = list(app.query(InterruptWidget))
        first.query_one("#approve").press()
        await pilot.pause(0.3)
        assert len(client.calls) == 1  # one of two answered: do not resume yet
        second.query_one("#reject").press()
        await pilot.pause(0.5)
    assert client.calls[1][2] == [
        {"interruptId": "a", "status": "resolved", "payload": {"approved": True}},
        {"interruptId": "b", "status": "resolved", "payload": {"approved": False}},
    ]


async def test_unsupported_schema_only_offers_cancel():
    from gentui.tui.widgets.interrupt import InterruptWidget

    run = [RunStartedEvent(thread_id="t", run_id="r"), interrupt_finish(
        {"id": "x", "reason": "input_required", "message": "Which region?",
         "response_schema": {"type": "object", "properties": {"region": {"type": "string"}}, "required": ["region"]}})]
    client = ResumeClient(run, [RunStartedEvent(thread_id="t", run_id="r2"), RunFinishedEvent(thread_id="t", run_id="r2")])
    app = GentuiApp(client)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"go", "enter")
        await pilot.pause(0.5)
        w = app.query_one(InterruptWidget)
        assert not w.query("#approve") and w.query("#cancel")
        w.query_one("#cancel").press()
        await pilot.pause(0.5)
    assert client.calls[1][2] == [{"interruptId": "x", "status": "cancelled"}]


async def test_client_sends_resume_with_no_messages():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=b"")

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    httpx.AsyncClient = lambda **kw: real(transport=transport, **kw)  # type: ignore[assignment]
    try:
        entries = [{"interruptId": "i1", "status": "resolved", "payload": {"approved": True}}]
        [e async for e in AguiClient("http://x/agent").run("t", "", None, entries)]
    finally:
        httpx.AsyncClient = real  # type: ignore[assignment]
    assert seen["messages"] == [] and seen["resume"] == entries


# -- conversation history sent to the backend ---------------------------------------------------


def _sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


async def _two_runs(send_history):
    bodies = []
    first = _sse(
        {"type": "RUN_STARTED", "threadId": "t", "runId": "r1"},
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "get_weather"},
        {"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"city": "Paris"}'},
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {"type": "TOOL_CALL_RESULT", "messageId": "tm1", "toolCallId": "c1", "content": "sunny", "role": "tool"},
        {"type": "TEXT_MESSAGE_START", "messageId": "a1", "role": "assistant"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "a1", "delta": "Sunny "},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "a1", "delta": "in Paris."},
        {"type": "TEXT_MESSAGE_END", "messageId": "a1"},
        {"type": "RUN_FINISHED", "threadId": "t", "runId": "r1"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=first if len(bodies) == 1 else b"")

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    httpx.AsyncClient = lambda **kw: real(transport=transport, **kw)  # type: ignore[assignment]
    try:
        kwargs = {} if send_history is None else {"send_history": send_history}
        client = AguiClient("http://x/agent", **kwargs)
        [e async for e in client.run("t", "weather in Paris?")]
        [e async for e in client.run("t", "and tomorrow?")]
    finally:
        httpx.AsyncClient = real  # type: ignore[assignment]
    return bodies


async def test_client_sends_the_whole_conversation_when_send_history_is_on():
    first, second = await _two_runs(send_history=True)
    assert [m["role"] for m in first["messages"]] == ["user"]
    msgs = second["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant", "user"]
    assert msgs[0]["content"] == "weather in Paris?" and msgs[-1]["content"] == "and tomorrow?"
    call = msgs[1]["toolCalls"][0]
    assert call["id"] == "c1" and call["function"] == {"name": "get_weather", "arguments": '{"city": "Paris"}'}
    assert msgs[2]["toolCallId"] == "c1" and msgs[2]["content"] == "sunny"
    assert msgs[3]["content"] == "Sunny in Paris."


async def test_by_default_only_the_newest_message_is_sent():
    first, second = await _two_runs(send_history=None)
    assert [m["content"] for m in second["messages"]] == ["and tomorrow?"]
    assert AguiClient("http://x").send_history is False and Config().send_history is False


async def test_a_new_thread_starts_with_empty_history():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=b"")

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    httpx.AsyncClient = lambda **kw: real(transport=transport, **kw)  # type: ignore[assignment]
    try:
        client = AguiClient("http://x/agent", send_history=True)
        [e async for e in client.run("one", "hello")]
        [e async for e in client.run("two", "fresh")]
    finally:
        httpx.AsyncClient = real  # type: ignore[assignment]
    assert [m["content"] for m in bodies[1]["messages"]] == ["fresh"]


# -- chat look: timestamps and markers ------------------------------------------------------------


async def test_every_message_shows_its_time_and_marker():
    import re

    run = [
        RunStartedEvent(thread_id="t", run_id="r"),
        TextMessageStartEvent(message_id="a", role="assistant"),
        TextMessageContentEvent(message_id="a", delta="hello"),
        TextMessageEndEvent(message_id="a"),
        RunFinishedEvent(thread_id="t", run_id="r"),
    ]
    app = GentuiApp(ScriptClient(*run))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press(*"hi", "enter")
        await pilot.pause(0.5)
        times = [str(t.render()) for t in app.query(".time")]
        assert len(times) == 2 and all(re.fullmatch(r"\d\d:\d\d", t) for t in times)  # you + the agent
        marks = [str(m.render()) for m in app.query(".mark")]
        assert [m.strip() for m in marks] == ["❯", "◈"]


async def test_timestamps_can_be_turned_off():
    app = GentuiApp(ScriptClient(), Config(show_time=False))
    async with app.run_test() as pilot:
        await pilot.press(*"hi", "enter")
        await pilot.pause(0.3)
        assert not app.query(".time")


async def test_failed_proposal_card_is_disabled_not_live():
    from textual.widgets import Button

    err = "Error: Validation failed for input parameters: 1 validation error for Propose_commandTool"
    run = [
        RunStartedEvent(thread_id="t", run_id="r"),
        ToolCallStartEvent(tool_call_id="bad", tool_call_name="propose_command"),
        ToolCallArgsEvent(tool_call_id="bad", delta=json.dumps({"command": "date", "explanation": "x", "risk": "read-only"})),
        ToolCallEndEvent(tool_call_id="bad"),
        ToolCallResultEvent(message_id="m", tool_call_id="bad", content=err, role="tool"),
        RunFinishedEvent(thread_id="t", run_id="r"),
    ]
    app = GentuiApp(ScriptClient(*run))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press(*"q", "enter")
        await pilot.pause(0.5)
        card = app.query_one("CommandWidget")
        assert card.state == "failed"
        assert all(b.disabled for b in card.query(Button))


# -- branding and startup splash ----------------------------------------------------------------


class SplashApp(GentuiApp):
    SPLASH_IN_HEADLESS = True
    SPLASH_SECONDS = 0.4


async def test_splash_shows_on_start_then_closes_by_itself():
    from gentui.tui.splash import SplashScreen

    app = SplashApp(ScriptClient())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, SplashScreen)
        await pilot.pause(0.8)
        assert not isinstance(app.screen, SplashScreen)
        assert app.focused is app.query_one("#prompt")  # ready to type


async def test_any_key_skips_the_splash_and_is_not_typed_into_the_prompt():
    from gentui.tui.splash import SplashScreen

    class LongSplash(SplashApp):
        SPLASH_SECONDS = 30

    app = LongSplash(ScriptClient())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.1)
        assert isinstance(app.screen, SplashScreen)
        await pilot.press("x")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, SplashScreen)
        assert app.query_one("#prompt").value == ""


async def test_splash_can_be_disabled_in_config():
    from gentui.tui.splash import SplashScreen

    app = SplashApp(ScriptClient(), Config(splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        assert not isinstance(app.screen, SplashScreen)


def test_logo_animation_reveals_then_fills_and_sweeps():
    from gentui.tui import branding

    mark = branding.WORDMARK_BIG
    assert branding.logo_frame(mark, 0.0).plain.strip() == ""  # nothing yet
    half = branding.logo_frame(mark, 0.45).plain
    full = branding.logo_frame(mark, 5.0).plain
    assert 0 < len(half.replace(" ", "").replace("\n", "")) < len(full.replace(" ", "").replace("\n", ""))
    assert full == mark  # the finished frame is exactly the wordmark
    # the highlight moves between frames
    assert branding.logo_frame(mark, 1.2).spans != branding.logo_frame(mark, 1.4).spans


def test_branding_helpers():
    from gentui.tui import branding

    assert branding.blend("#000000", "#ffffff", 0.5) == "#808080"
    assert branding.blend("#102030", "#102030", 0.7) == "#102030"
    assert branding.wordmark_for(120) == branding.WORDMARK_BIG
    assert branding.wordmark_for(40) == branding.WORDMARK_SMALL  # narrow terminals get the small one
    label = branding.thinking_label(4.2, now=1.0)
    assert "Thinking…" in label.plain and "(4s)" in label.plain
    assert branding.thinking_label(1, now=1.0).spans != branding.thinking_label(1, now=1.3).spans  # animates


async def test_logo_stays_after_the_splash_static_and_survives_clear():
    from gentui.tui import branding

    app = SplashApp(ScriptClient())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(1.0)  # splash is over
        brand = app.query_one("#brand", Static)
        before = str(brand.render())
        assert "██" in before or "┏" in before  # the wordmark is on screen
        await pilot.pause(0.5)
        assert str(brand.render()) == before  # static: it does not animate or disappear
        await pilot.press(*"/clear", "enter")
        await pilot.pause(0.3)
        assert app.query("#brand") and app.query("#welcome")  # /clear keeps the logo


async def test_logo_can_be_turned_off():
    app = GentuiApp(ScriptClient(), Config(logo=False))
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert not app.query("#brand") and app.query("#welcome")


def test_static_logo_is_the_full_wordmark_without_a_highlight_sweep():
    from gentui.tui import branding

    a, b = branding.logo_static(branding.WORDMARK_BIG), branding.logo_static(branding.WORDMARK_BIG)
    assert a.plain == branding.WORDMARK_BIG and a.spans == b.spans


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli_main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("gentui ")
