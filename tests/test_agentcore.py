"""Agents on Amazon Bedrock AgentCore Runtime (AG-UI protocol), invoked with boto3.

boto3 is replaced by a fake client; the streaming body is botocore's real StreamingBody."""

import asyncio
import io
import json
import threading

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.response import StreamingBody

from gentui.cli import main as cli_main
from gentui.config import Config, load_config, parse_runtime_arn
from gentui.tui import agentcore_client
from gentui.tui.agentcore_client import AgentCoreClient, session_id_for
from gentui.tui.agui_client import BackendError
from gentui.tui.app import GentuiApp

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my_agent-AbCdEfGhIj"


def sse(*events) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


RUN = sse(
    {"type": "RUN_STARTED", "threadId": "t", "runId": "r"},
    {"type": "TEXT_MESSAGE_START", "messageId": "a1", "role": "assistant"},
    {"type": "TEXT_MESSAGE_CONTENT", "messageId": "a1", "delta": "Hello "},
    {"type": "TEXT_MESSAGE_CONTENT", "messageId": "a1", "delta": "from AgentCore"},
    {"type": "TEXT_MESSAGE_END", "messageId": "a1"},
    {"type": "RUN_FINISHED", "threadId": "t", "runId": "r"},
)


class Body(StreamingBody):
    chunk_sizes: list[int]

    def iter_lines(self, chunk_size=1024, keepends=False):
        self.__dict__.setdefault("chunk_sizes", []).append(chunk_size)
        return super().iter_lines(chunk_size, keepends)


class FakeAgentCore:
    """Stands in for boto3.client("bedrock-agentcore")."""

    def __init__(self, data=RUN, content_type="text/event-stream", errors=()):
        self.data, self.content_type, self.errors = data, content_type, list(errors)
        self.calls, self.bodies = [], []

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        body = Body(io.BytesIO(self.data), len(self.data))
        self.bodies.append(body)
        return {"response": body, "contentType": self.content_type, "statusCode": 200,
                "runtimeSessionId": kwargs["runtimeSessionId"]}


def client_error(code, message="boom"):
    return ClientError({"Error": {"Code": code, "Message": message}}, "InvokeAgentRuntime")


async def collect(client, text="hi", **kw):
    return [e async for e in client.run("thread-1", text, **kw)]


# -- ARN and config -----------------------------------------------------------------------------


def test_runtime_arn_parsing():
    assert parse_runtime_arn(ARN) == ("us-east-1", "123456789012")
    assert parse_runtime_arn("arn:aws-us-gov:bedrock-agentcore:us-gov-west-1:123456789012:runtime/x-1") == ("us-gov-west-1", "123456789012")
    for bad in ("", "http://localhost:8000/agent", "arn:aws:s3:::bucket", "arn:aws:bedrock-agentcore:us-east-1:12:runtime/x",
                "arn:aws:bedrock-agentcore:us-east-1:123456789012:memory/x"):
        with pytest.raises(ValueError, match="AgentCore runtime ARN"):
            parse_runtime_arn(bad)


def test_config_arn_from_override_env_and_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GENTUI_AGENTCORE_ARN", raising=False)
    assert load_config().agentcore_arn is None
    assert load_config(agentcore_arn=ARN).agentcore_arn == ARN
    monkeypatch.setenv("GENTUI_AGENTCORE_ARN", ARN)
    assert load_config().agentcore_arn == ARN
    monkeypatch.delenv("GENTUI_AGENTCORE_ARN")
    (tmp_path / "gentui.toml").write_text(f'agentcore_arn = "{ARN}"\nregion = "eu-west-1"\nqualifier = "prod"\naws_profile = "dev"\n')
    cfg = load_config()
    assert (cfg.agentcore_arn, cfg.region, cfg.qualifier, cfg.aws_profile) == (ARN, "eu-west-1", "prod", "dev")


def test_config_rejects_a_malformed_arn_and_target_prefers_the_arn():
    with pytest.raises(ValueError, match="AgentCore runtime ARN"):
        load_config(agentcore_arn="not-an-arn")
    assert Config().target == "http://localhost:8000/agent"
    assert Config(agentcore_arn=ARN).target == ARN
    assert ARN in Config(agentcore_arn=ARN).welcome_text


# -- session ids ----------------------------------------------------------------------------------


@pytest.mark.parametrize("thread", ["t", "a", "x" * 5, "thread with spaces/and:odd*chars", "7f1c2d3e-aaaa-bbbb-cccc-1234567890ab", "y" * 500])
def test_session_ids_are_valid_stable_and_distinct(thread):
    sid = session_id_for(thread)
    assert 33 <= len(sid) <= 256
    assert all(c.isalnum() or c in "-_" for c in sid)
    assert sid == session_id_for(thread)


def test_different_threads_get_different_sessions():
    assert session_id_for("one") != session_id_for("two")


# -- the request --------------------------------------------------------------------------------


async def test_request_is_a_run_agent_input_sent_with_the_right_arguments():
    fake = FakeAgentCore()
    client = AgentCoreClient(ARN, client=fake)
    events = await collect(client, "hello agent", forwarded_props={"model": "fast"})

    assert [e.type.value for e in events][0] == "RUN_STARTED" and events[-1].type.value == "RUN_FINISHED"
    (call,) = fake.calls
    assert call["agentRuntimeArn"] == ARN
    assert call["contentType"] == "application/json" and call["accept"] == "text/event-stream"
    assert 33 <= len(call["runtimeSessionId"]) <= 256 and call["runtimeSessionId"] == session_id_for("thread-1")
    assert "qualifier" not in call  # the runtime's default endpoint
    body = json.loads(call["payload"])
    assert body["threadId"] == "thread-1" and body["forwardedProps"] == {"model": "fast"}
    assert [(m["role"], m["content"]) for m in body["messages"]] == [("user", "hello agent")]


async def test_qualifier_is_passed_when_set():
    fake = FakeAgentCore()
    await collect(AgentCoreClient(ARN, qualifier="prod", client=fake))
    assert fake.calls[0]["qualifier"] == "prod"


async def test_same_thread_reuses_the_session_new_thread_gets_a_new_one():
    fake = FakeAgentCore()
    client = AgentCoreClient(ARN, client=fake)
    [e async for e in client.run("alpha-thread", "one")]
    [e async for e in client.run("alpha-thread", "two")]
    [e async for e in client.run("beta-thread", "three")]
    a, b, c = (call["runtimeSessionId"] for call in fake.calls)
    assert a == b != c


async def test_resume_sends_no_message_and_the_resume_entries():
    fake = FakeAgentCore()
    entries = [{"interruptId": "approve-c1", "status": "resolved", "payload": {"approved": True}}]
    [e async for e in AgentCoreClient(ARN, client=fake).run("t", "", None, entries)]
    body = json.loads(fake.calls[0]["payload"])
    assert body["messages"] == [] and body["resume"] == entries


async def test_send_history_works_over_agentcore_too():
    fake = FakeAgentCore()
    client = AgentCoreClient(ARN, send_history=True, client=fake)
    await collect(client, "first")
    await collect(client, "second")
    roles = [m["role"] for m in json.loads(fake.calls[1]["payload"])["messages"]]
    assert roles == ["user", "assistant", "user"]


# -- the stream ---------------------------------------------------------------------------------------


async def test_stream_is_read_one_byte_at_a_time_so_events_are_not_held_back():
    fake = FakeAgentCore()
    await collect(AgentCoreClient(ARN, client=fake))
    assert fake.bodies[0].chunk_sizes == [1]


async def test_raw_payloads_reach_the_dev_pane_hook():
    seen = []
    client = AgentCoreClient(ARN, client=FakeAgentCore())
    client.on_raw = seen.append
    await collect(client)
    assert json.loads(seen[0])["type"] == "RUN_STARTED" and len(seen) == 6


async def test_unknown_events_and_noise_are_skipped():
    data = b": keepalive\n\n" + sse({"type": "SOMETHING_NEW"}) + RUN
    events = await collect(AgentCoreClient(ARN, client=FakeAgentCore(data=data)))
    assert events[0].type.value == "RUN_STARTED"


async def test_a_runtime_that_is_not_ag_ui_gets_a_clear_error():
    fake = FakeAgentCore(data=b'{"result": "plain json"}', content_type="application/json")
    with pytest.raises(BackendError) as exc:
        await collect(AgentCoreClient(ARN, client=fake))
    assert "AG-UI" in str(exc.value) and "serverProtocol AGUI" in str(exc.value) and "plain json" in str(exc.value)


async def test_closing_early_stops_the_reader_thread():
    many = sse(*[{"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "x"} for _ in range(2000)])
    client = AgentCoreClient(ARN, client=FakeAgentCore(data=many))
    gen = client._stream_lines({"threadId": "t"})
    await gen.__anext__()
    await gen.aclose()
    for _ in range(40):
        if not any(t.name == "agentcore-stream" for t in threading.enumerate()):
            break
        await asyncio.sleep(0.05)
    assert not any(t.name == "agentcore-stream" for t in threading.enumerate())


# -- errors ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("error,expected", [
    (client_error("AccessDeniedException"), "bedrock-agentcore:InvokeAgentRuntime"),
    (client_error("ResourceNotFoundException"), "Runtime not found"),
    (client_error("ThrottlingException"), "throttling"),
    (client_error("RuntimeClientError"), "CloudWatch"),
    (client_error("ValidationException", "bad session id"), "ValidationException: bad session id"),
    (client_error("ExpiredTokenException"), "aws sso login"),
    (NoCredentialsError(), "No AWS credentials found"),
])
async def test_aws_errors_become_actionable_messages(error, expected):
    client = AgentCoreClient(ARN, client=FakeAgentCore(errors=[error]))
    with pytest.raises(BackendError, match=expected):
        await collect(client)


async def test_session_busy_is_retried_with_backoff_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(agentcore_client.time, "sleep", sleeps.append)
    fake = FakeAgentCore(errors=[client_error("RetryableConflictException"), client_error("RetryableConflictException")])
    events = await collect(AgentCoreClient(ARN, client=fake))
    assert len(fake.calls) == 3 and events[-1].type.value == "RUN_FINISHED"
    assert sleeps == [0.5, 1.0]


async def test_session_busy_gives_up_after_a_few_tries(monkeypatch):
    monkeypatch.setattr(agentcore_client.time, "sleep", lambda s: None)
    fake = FakeAgentCore(errors=[client_error("RetryableConflictException")] * 10)
    with pytest.raises(BackendError, match="busy"):
        await collect(AgentCoreClient(ARN, client=fake))
    assert len(fake.calls) == 4  # the first try plus three retries


# -- boto3 is optional ---------------------------------------------------------------------------------------


def test_missing_boto3_raises_import_error(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "boto3", None)
    with pytest.raises(ImportError):
        AgentCoreClient(ARN)


def test_cli_explains_how_to_install_boto3(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "boto3", None)
    with pytest.raises(SystemExit) as exc:
        cli_main([ARN])
    assert "boto3" in str(exc.value) and "agentcore" in str(exc.value)


# -- CLI --------------------------------------------------------------------------------------------------------------


@pytest.fixture
def launched(monkeypatch):
    """Run the CLI without opening the UI or touching AWS; return the (client, config) it built."""
    built = []
    monkeypatch.setattr(AgentCoreClient, "_make_client", staticmethod(lambda region, profile, timeout: ("fake-client", region, profile)))
    monkeypatch.setattr(GentuiApp, "run", lambda self: built.append((self.client, self.config)))
    monkeypatch.delenv("GENTUI_AGENTCORE_ARN", raising=False)
    monkeypatch.chdir(__import__("tempfile").mkdtemp())
    return built


def test_cli_positional_arn_selects_agentcore(launched):
    cli_main([ARN, "--profile", "dev", "--qualifier", "prod"])
    ((client, config),) = launched
    assert isinstance(client, AgentCoreClient) and client.arn == ARN and client.qualifier == "prod"
    assert client._client == ("fake-client", "us-east-1", "dev")  # region comes from the ARN
    assert config.target == ARN


def test_cli_flag_and_region_override(launched):
    cli_main(["--agentcore-arn", ARN, "--region", "eu-west-1"])
    ((client, _),) = launched
    assert client._client[1] == "eu-west-1"


def test_cli_plain_url_still_uses_http(launched):
    from gentui.tui.agui_client import AguiClient

    cli_main(["http://localhost:9999/agent"])
    ((client, _),) = launched
    assert type(client) is AguiClient and client.url == "http://localhost:9999/agent"


def test_cli_rejects_a_bad_arn(launched):
    with pytest.raises(SystemExit) as exc:
        cli_main(["--agentcore-arn", "arn:aws:s3:::nope"])
    assert "AgentCore runtime ARN" in str(exc.value)


# -- in the app ------------------------------------------------------------------------------------------------------------


async def test_chat_works_end_to_end_through_the_app():
    from textual.widgets import Markdown

    app = GentuiApp(AgentCoreClient(ARN, client=FakeAgentCore()), Config(agentcore_arn=ARN, splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press(*"hi", "enter")
        await pilot.pause(1.0)
        assert any("Hello from AgentCore" in m.source for m in app.query(Markdown))
        assert ARN in str(app.query_one("#statusbar .right").render())


async def test_aws_errors_show_in_the_chat_not_a_crash():
    fake = FakeAgentCore(errors=[client_error("AccessDeniedException")])
    app = GentuiApp(AgentCoreClient(ARN, client=fake), Config(agentcore_arn=ARN, splash=False))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press(*"hi", "enter")
        await pilot.pause(1.0)
        assert any("InvokeAgentRuntime" in str(e.render()) for e in app.query(".error"))


def test_profile_and_region_from_the_config_file_reach_boto3(launched, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gentui.toml").write_text(f'agentcore_arn = "{ARN}"\naws_profile = "work"\nregion = "ap-south-1"\n')
    cli_main([])
    ((client, _),) = launched
    assert client._client == ("fake-client", "ap-south-1", "work")


def test_profile_and_region_are_optional(launched):
    cli_main([ARN])
    ((client, _),) = launched
    assert client._client == ("fake-client", "us-east-1", None)  # ARN region, default credential chain


# -- endpoint ARNs (.../runtime-endpoint/DEFAULT) -----------------------------------------------------------


ENDPOINT_ARN = ARN + "/runtime-endpoint/DEFAULT"


def test_an_endpoint_arn_is_accepted_and_split_into_runtime_and_endpoint():
    from gentui.config import split_runtime_arn

    assert parse_runtime_arn(ENDPOINT_ARN) == ("us-east-1", "123456789012")
    assert split_runtime_arn(ENDPOINT_ARN) == (ARN, "DEFAULT")
    assert split_runtime_arn(ARN) == (ARN, None)
    assert split_runtime_arn(ARN + "/runtime-endpoint/prod") == (ARN, "prod")
    for bad in (ARN + "/runtime-endpoint/", ARN + "/runtime-endpoint/a/b", ARN + "/other/x"):
        with pytest.raises(ValueError, match="AgentCore runtime ARN"):
            parse_runtime_arn(bad)


async def test_the_api_gets_the_plain_runtime_arn_and_the_endpoint_as_qualifier():
    fake = FakeAgentCore()
    await collect(AgentCoreClient(ENDPOINT_ARN, client=fake))
    assert fake.calls[0]["agentRuntimeArn"] == ARN  # never the endpoint ARN: AWS rejects that
    assert fake.calls[0]["qualifier"] == "DEFAULT"


async def test_an_explicit_matching_qualifier_is_fine_and_a_conflicting_one_is_an_error():
    fake = FakeAgentCore()
    await collect(AgentCoreClient(ENDPOINT_ARN, qualifier="DEFAULT", client=fake))
    assert fake.calls[0]["qualifier"] == "DEFAULT"
    with pytest.raises(ValueError, match="names endpoint 'DEFAULT' but --qualifier is 'prod'"):
        AgentCoreClient(ENDPOINT_ARN, qualifier="prod", client=FakeAgentCore())


def test_cli_accepts_an_endpoint_arn(launched):
    cli_main([ENDPOINT_ARN])
    ((client, config),) = launched
    assert client.arn == ARN and client.qualifier == "DEFAULT" and config.agentcore_arn == ENDPOINT_ARN


def test_cli_reports_conflicting_endpoint_and_qualifier(launched):
    with pytest.raises(SystemExit) as exc:
        cli_main([ENDPOINT_ARN, "--qualifier", "prod"])
    assert "use only one" in str(exc.value)


async def test_the_request_validates_against_the_real_service_model_for_an_endpoint_arn(monkeypatch):
    """Same as production: a real boto3 client, with botocore's Stubber checking the parameters."""
    import io as _io
    from botocore.stub import ANY, Stubber

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "y")
    client = AgentCoreClient(ENDPOINT_ARN)
    data = sse({"type": "RUN_STARTED", "threadId": "t", "runId": "r"})
    with Stubber(client._client) as stub:
        stub.add_response(
            "invoke_agent_runtime",
            {"response": StreamingBody(_io.BytesIO(data), len(data)), "contentType": "text/event-stream", "statusCode": 200},
            expected_params={"agentRuntimeArn": ARN, "qualifier": "DEFAULT", "runtimeSessionId": ANY,
                             "contentType": "application/json", "accept": "text/event-stream", "payload": ANY},
        )
        assert [e.type.value async for e in client.run("t", "hi")] == ["RUN_STARTED"]
        stub.assert_no_pending_responses()
