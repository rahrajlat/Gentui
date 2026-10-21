"""`gentui --serve`: the browser session runs the same command minus the serve flags."""

import sys

import pytest

from gentui import cli


@pytest.mark.parametrize("argv, kept", [
    (["http://x/agent", "--serve"], ["http://x/agent"]),
    (["--serve", "--port", "9000", "--host", "0.0.0.0", "--demo", "all"], ["--demo", "all"]),
    (["--port=9000", "--host=h", "--serve", "-H", "A: b", "url"], ["-H", "A: b", "url"]),
    (["--serve", "--token", "t", "--dev"], ["--token", "t", "--dev"]),
])
def test_serve_flags_are_removed_from_the_session_command(argv, kept):
    assert cli._without_serve_flags(argv) == kept


def test_serve_starts_textual_serve_with_the_gentui_command(monkeypatch):
    textual_serve = pytest.importorskip("textual_serve.server")
    seen = {}

    class FakeServer:
        def __init__(self, command, **kwargs):
            seen["command"], seen["kwargs"] = command, kwargs

        def serve(self):
            seen["served"] = True

    monkeypatch.setattr(textual_serve, "Server", FakeServer)
    cli.main(["http://x/agent", "--serve", "--port", "9001"])
    assert seen["command"] == f"{sys.executable} -m gentui.cli http://x/agent"
    assert seen["kwargs"]["port"] == 9001 and seen["kwargs"]["host"] == "localhost" and seen["served"]
