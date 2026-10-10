"""Judges for --compare: the plugin API, the Ollama judge, the cache, and the verdicts in the compare view."""

import json
from pathlib import Path

import httpx
import pytest
from textual.widgets import Select, Static

from gentui import judge, plugins, session
from gentui.config import Config
from gentui.tui.compare import CompareApp
from tests.test_session import record


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(plugins, "JUDGES", dict(plugins.JUDGES))


CASE = judge.Case("hi", "left answer", "right answer")


def test_judges_can_return_a_dict_a_tuple_or_a_verdict():
    assert judge.as_verdict({"score": 0.5, "reason": "ok"}).score == 0.5
    assert judge.as_verdict((2, "clamped")).score == 1.0
    assert judge.as_verdict(judge.Verdict(0.1, "x")).reason == "x"
    with pytest.raises(ValueError):
        judge.as_verdict("nonsense")


async def test_verdicts_are_cached_and_failures_are_not():
    calls = []

    @plugins.register_judge("mine")
    async def mine(case):
        calls.append(case)
        return {"score": 0.8, "reason": "fine"}

    first, second = await judge.judge_case("mine", CASE), await judge.judge_case("mine", CASE)
    assert (first.score, first.cached, second.cached) == (0.8, False, True) and len(calls) == 1

    @plugins.register_judge("broken")
    def broken(case):
        raise RuntimeError("boom")

    verdict = await judge.judge_case("broken", CASE)
    assert verdict.failed and "boom" in verdict.reason
    assert (await judge.judge_case("nope", CASE)).failed


async def test_ollama_judge_posts_the_rubric_and_reads_the_json(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": '{"score": 0.4, "reason": "the numbers differ"}'}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    verdict = await judge.ollama_judge_for("gpt-oss:120b")(judge.Case("p", "A text", "B text", [{"name": "ls", "args": "{}", "result": "x"}]))
    assert (verdict.score, verdict.reason) == (0.4, "the numbers differ")
    assert seen["auth"] == "Bearer k" and seen["body"]["stream"] is False and seen["body"]["options"] == {"temperature": 0}
    assert "A text" in seen["body"]["messages"][1]["content"] and "ls(" in seen["body"]["messages"][1]["content"]


async def test_ollama_cloud_needs_a_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    verdict = await judge.judge_case(judge.register_ollama("gpt-oss:120b"), CASE)
    assert verdict.failed and "OLLAMA_API_KEY" in verdict.reason


async def test_compare_view_shows_each_prompts_score_and_comment(tmp_path: Path):
    await record(tmp_path / "a.json", "chat")
    await record(tmp_path / "b.json", "approval")

    @plugins.register_judge("fake")
    async def fake(case):
        return {"score": 0.25, "reason": f"A said {len(case.left)} chars, B {len(case.right)}"}

    sessions = [session.load(tmp_path / "a.json"), session.load(tmp_path / "b.json")]
    app = CompareApp(sessions, Config(), judge="fake")
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(1.0)
        assert app.query_one("#pick-judge", Select).value == "fake"
        verdicts = [str(v.render()) for v in app.query(".verdict") if v.display]
        assert verdicts and all("25% match" in v and "A said" in v for v in verdicts)
        panels = [v for v in app.query(".verdict") if v.display]
        assert all(v.has_class("bad") and "fake" in str(v.border_title) for v in panels)
        # each panel opens its prompt's section: it sits right above that prompt's first row
        for panel in panels:
            turn = panel.name
            first = next(r for r in app.query(".pair") if r.has_class(f"turn-{turn}"))
            assert panel.region.y < first.region.y
        assert "judge average 25%" in str(app.query_one("#summary", Static).render())
        app.query_one("#pick-judge", Select).value = 0  # off again: the verdicts go away
        await pilot.pause(0.3)
        assert not any(v.display for v in app.query(".verdict"))


def test_cloud_models_go_through_the_local_ollama_and_others_to_ollama_com(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert judge.ollama_host("gpt-oss:120b-cloud") == "http://localhost:11434"
    assert judge.ollama_host("gpt-oss:120b") == "https://ollama.com"
    monkeypatch.setenv("OLLAMA_HOST", "myserver:11434")
    assert judge.ollama_host("gpt-oss:120b-cloud") == "http://myserver:11434"
