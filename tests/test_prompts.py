"""--prompts: a YAML file of messages sent one after the other."""

import pytest
from ag_ui.core import RunFinishedEvent, RunStartedEvent, TextMessageContentEvent, TextMessageEndEvent, TextMessageStartEvent

from gentui import prompts
from gentui.cli import main
from gentui.config import Config
from gentui.session import Recorder, load
from gentui.tui.app import GentuiApp


def write(tmp_path, text):
    path = tmp_path / "p.yml"
    path.write_text(text)
    return path


def test_prompts_can_be_a_list_or_a_mapping_with_text_keys(tmp_path):
    assert prompts.load(write(tmp_path, "prompts:\n  - one\n  - text: two\n")) == ["one", "two"]
    assert prompts.load(write(tmp_path, "- one\n- two\n")) == ["one", "two"]


@pytest.mark.parametrize("text", ["", "prompts: []", "prompts: hello", "prompts:\n  - 3", "a: [", "prompts:\n  - text: ''"])
def test_bad_prompts_files_are_refused(tmp_path, text):
    with pytest.raises(prompts.PromptsError):
        prompts.load(write(tmp_path, text))


def test_missing_prompts_file_is_refused(tmp_path):
    with pytest.raises(prompts.PromptsError, match="cannot read"):
        prompts.load(tmp_path / "nope.yml")


def test_cli_rejects_a_bad_prompts_file(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--prompts", str(tmp_path / "nope.yml")])
    assert "cannot read" in str(exc.value)


def test_cli_refuses_compare_with_record(tmp_path):
    with pytest.raises(SystemExit):
        main(["--compare", "a,b", "--record", "x"])


class EchoClient:
    def __init__(self):
        self.sent = []

    async def run(self, thread_id, text, forwarded_props=None):
        self.sent.append(text)
        yield RunStartedEvent(thread_id=thread_id, run_id="r")
        yield TextMessageStartEvent(message_id="m" + str(len(self.sent)), role="assistant")
        yield TextMessageContentEvent(message_id="m" + str(len(self.sent)), delta=f"echo {text}")
        yield TextMessageEndEvent(message_id="m" + str(len(self.sent)))
        yield RunFinishedEvent(thread_id=thread_id, run_id="r")


async def test_queued_prompts_are_sent_in_order_and_recorded(tmp_path):
    client = EchoClient()
    app = GentuiApp(client, Config(splash=False))
    app.queued_prompts = ["first", "second", "third"]
    app.recorder = Recorder(tmp_path / "run.json")
    async with app.run_test() as pilot:
        for _ in range(100):
            await pilot.pause(0.1)
            if len(client.sent) == 3 and not app._busy:
                break
    assert client.sent == ["first", "second", "third"]
    items = load(tmp_path / "run.json").items
    assert [i.data["text"] for i in items if i.kind == "user"] == ["first", "second", "third"]
