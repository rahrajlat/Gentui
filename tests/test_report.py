"""Exporting a comparison to HTML: charts, tables, judge panels, and the `e` key / --export."""

import re
from pathlib import Path

import pytest

from gentui import plugins, report, session
from gentui.cli import main
from gentui.config import Config
from gentui.tui.compare import Block, CompareApp, align
from tests.test_session import record


def chart(values, kind="bar"):
    return Block("tool", name="show_chart", result="ok",
                 args='{"type": "%s", "title": "T <b>", "x": ["a", "b", "c"], "series": [{"name": "s", "values": %s}]}' % (kind, values))


@pytest.mark.parametrize("kind", ["bar", "line", "scatter", "histogram"])
def test_every_chart_type_becomes_an_svg(kind):
    svg = report.chart_svg({"type": kind, "title": "T", "x": [1, 2, 3], "series": [{"name": "s", "values": [3, 1, 2]}, {"name": "u", "values": [1, 2, 3]}]})
    assert svg.startswith("<svg") and svg.endswith("</svg>") and ("<rect" in svg or "<circle" in svg)


def test_a_bad_chart_is_reported_not_fatal():
    with pytest.raises(ValueError):
        report.chart_svg({"type": "pie", "series": [{"values": [1]}]})
    page = report.render("a", "b", align([Block("tool", name="show_chart", args='{"type": "pie"}')], []), {}, None)
    assert "Could not draw" in page


def test_report_has_charts_tables_marks_and_escapes_everything():
    left = [Block("user", "hi"), Block("text", "disk is **78%** full <script>alert(1)</script>"), chart([1, 2, 3])]
    right = [Block("user", "hi"), Block("text", "disk is **98%** full"), chart([3, 2, 1]),
             Block("tool", name="show_table", args='{"title": "Disk", "columns": ["m", "%"], "rows": [["/", "98%"]]}', result="ok")]
    page = report.render("v1", "v2", align(left, right), {}, None)
    assert page.count("<svg") == 2 and "<table>" in page and "<del>" in page and "<ins>" in page
    assert "<script>" not in page and "&lt;script&gt;" in page  # an answer can never inject markup
    assert "cell changed" in page and "cell added" in page and "T &lt;b&gt;" in page


def test_judge_panels_open_each_prompt():
    from gentui.judge import Verdict

    pairs = align([Block("user", "one"), Block("user", "two")], [Block("user", "one"), Block("user", "two")])
    page = report.render("a", "b", pairs, {1: Verdict(0.9, "same"), 2: Verdict(0.2, "<b>differs</b>")}, "my-judge")
    assert page.index("Prompt 1") < page.index("90% match") < page.index("Prompt 2") < page.index("20% match")
    assert "judge good" in page and "judge bad" in page and "&lt;b&gt;differs" in page and "judge average <b>55%</b>" in page


async def test_build_judges_every_changed_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(plugins, "JUDGES", dict(plugins.JUDGES))
    await record(tmp_path / "a.json", "chat")
    await record(tmp_path / "b.json", "approval")
    seen = []

    @plugins.register_judge("fake")
    def fake(case):
        seen.append(case.prompt)
        return {"score": 0.5, "reason": "meh"}

    page = await report.build(session.load(tmp_path / "a.json"), session.load(tmp_path / "b.json"), "fake")
    assert seen and "50% match" in page and re.search(r"<svg|<table|tool-name", page)


def test_save_never_overwrites(tmp_path):
    first = report.save(tmp_path / "r.html", "1")
    second = report.save(tmp_path / "r.html", "2")
    assert (first.name, second.name) == ("r.html", "r-1.html") and first.read_text() == "1"


async def test_e_key_exports_from_the_compare_view(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    await record(tmp_path / "a.json", "chat")
    await record(tmp_path / "b.json", "all")
    app = CompareApp([session.load(tmp_path / "a.json"), session.load(tmp_path / "b.json")], Config())
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.pause(0.5)
        await pilot.press("e")
        await pilot.pause(0.3)
    page = (tmp_path / "compare-a-vs-b.html").read_text()
    assert "<svg" in page and "Prompt 1" in page


def test_cli_export_writes_the_page_without_a_ui(tmp_path, monkeypatch, capsys):
    import asyncio

    asyncio.run(record(tmp_path / "a.json", "chat"))
    asyncio.run(record(tmp_path / "b.json", "approval"))
    monkeypatch.chdir(tmp_path)
    main(["--compare", "a,b", "--export", "out.html"])
    assert "Saved the comparison" in capsys.readouterr().out
    assert "<html" in (tmp_path / "out.html").read_text()
    with pytest.raises(SystemExit):
        main(["--export", "x.html"])
