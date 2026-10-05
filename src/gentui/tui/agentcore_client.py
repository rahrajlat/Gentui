"""Amazon Bedrock AgentCore Runtime transport.

An agent deployed on AgentCore Runtime with the **AG-UI protocol** accepts a `RunAgentInput` on
`/invocations` and answers with an SSE stream of AG-UI events. This client sends that request with
boto3's `invoke_agent_runtime` (so AWS credentials and SigV4 signing just work) and feeds the stream
into the same event handling as the plain HTTP client.

Needs boto3: `pip install 'gentui[agentcore]'`.
"""

import asyncio
import hashlib
import re
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from gentui.config import parse_runtime_arn, split_runtime_arn
from gentui.tui.agui_client import AguiClient, BackendError

_DONE = object()
_RETRIES = 3  # for RetryableConflictException ("session busy"); AG-UI clients are expected to retry it
_SESSION_MIN, _SESSION_MAX = 33, 256  # the API's limits for runtimeSessionId


def session_id_for(thread_id: str) -> str:
    """A stable AgentCore runtime session id for a Gentui conversation.

    AgentCore keeps one isolated session (and its state) per id, so one thread = one session. The API
    requires 33 to 256 characters, so short or odd thread ids are made safe and padded with a hash."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "-", thread_id)
    sid = f"gentui-{clean}"
    if len(sid) < _SESSION_MIN:
        sid = f"{sid}-{hashlib.sha256(thread_id.encode()).hexdigest()}"
    return sid[:_SESSION_MAX]


def explain(exc: BaseException) -> BackendError:
    """Turn a boto3 / botocore exception into a message that tells the user what to do."""
    name = type(exc).__name__
    error = (getattr(exc, "response", None) or {}).get("Error", {})
    code, message = error.get("Code", name), error.get("Message", str(exc))
    if name in ("NoCredentialsError", "PartialCredentialsError"):
        return BackendError(
            "No AWS credentials found. Run `aws sso login`, or set AWS_PROFILE / "
            "AWS_ACCESS_KEY_ID, or pass --profile."
        )
    if code in ("ExpiredTokenException", "ExpiredToken", "UnrecognizedClientException", "InvalidSignatureException"):
        return BackendError(f"Your AWS credentials were rejected ({code}). Refresh them (e.g. `aws sso login`).")
    friendly = {
        "AccessDeniedException": "Access denied. The caller needs bedrock-agentcore:InvokeAgentRuntime on this "
        "runtime (and bedrock-agentcore:InvokeAgentRuntimeForUser if a user id is used).",
        "ResourceNotFoundException": "Runtime not found. Check the ARN, the region and --qualifier.",
        "ThrottlingException": "AgentCore is throttling requests. Wait a moment and try again.",
        "ServiceQuotaExceededException": "AgentCore service quota exceeded (too many sessions or requests).",
        "RuntimeClientError": "The agent code failed while running. Check the runtime's CloudWatch logs.",
        "RetryableConflictException": "The runtime session is busy (starting or finishing another call). Try again.",
    }
    if code in friendly:
        return BackendError(f"{friendly[code]} ({code})")
    if name in ("EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError"):
        return BackendError(f"Cannot reach AgentCore: {exc}")
    return BackendError(f"AgentCore error: {code}: {message}")


class AgentCoreClient(AguiClient):
    """Same interface and behaviour as `AguiClient`, but the transport is boto3 invoke_agent_runtime."""

    def __init__(
        self,
        arn: str,
        region: str | None = None,
        profile: str | None = None,
        qualifier: str | None = None,
        timeout: float | None = None,
        send_history: bool = False,
        client: Any = None,
    ) -> None:
        arn_region, _ = parse_runtime_arn(arn)  # ValueError for a malformed ARN
        runtime_arn, endpoint = split_runtime_arn(arn)
        if qualifier and endpoint and qualifier != endpoint:
            raise ValueError(f"the ARN names endpoint {endpoint!r} but --qualifier is {qualifier!r}; use only one")
        super().__init__(runtime_arn, None, timeout, send_history)
        self.arn = runtime_arn  # the API wants the plain runtime ARN ...
        self.qualifier = qualifier or endpoint  # ... and the endpoint as `qualifier`
        self._client = client if client is not None else self._make_client(region or arn_region, profile, timeout)

    @staticmethod
    def _make_client(region: str, profile: str | None, timeout: float | None) -> Any:
        import boto3  # optional dependency: ImportError is handled by the CLI with install instructions
        from botocore.config import Config
        from botocore.exceptions import ProfileNotFound

        try:
            session = boto3.Session(profile_name=profile, region_name=region)
        except ProfileNotFound as exc:
            raise BackendError(f"AWS profile {profile!r} was not found.") from exc
        # Agents can think for a long time without sending bytes; botocore needs a number, not None.
        config = Config(read_timeout=timeout or 3600, connect_timeout=10, retries={"max_attempts": 2, "mode": "standard"})
        return session.client("bedrock-agentcore", config=config)

    # -- transport -------------------------------------------------------------------------------

    async def _stream_lines(self, body: dict[str, Any]) -> AsyncIterator[str]:
        """boto3 is blocking, so the call and the stream read run in a thread that feeds a queue."""
        import json

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Any] = asyncio.Queue()
        stop = threading.Event()
        payload = json.dumps(body).encode()
        session_id = session_id_for(str(body.get("threadId", "")))

        def worker() -> None:
            try:
                for line in self._invoke(payload, session_id, stop):
                    loop.call_soon_threadsafe(queue.put_nowait, line)
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)
            except BaseException as exc:  # noqa: BLE001 - handed to the consumer, which re-raises
                loop.call_soon_threadsafe(queue.put_nowait, exc)

        threading.Thread(target=worker, daemon=True, name="agentcore-stream").start()
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stop.set()  # the consumer went away (app closed, run cancelled): stop reading

    def _invoke(self, payload: bytes, session_id: str, stop: threading.Event) -> Iterator[str]:
        request: dict[str, Any] = {
            "agentRuntimeArn": self.arn,
            "runtimeSessionId": session_id,
            "payload": payload,
            "contentType": "application/json",
            "accept": "text/event-stream",
        }
        if self.qualifier:
            request["qualifier"] = self.qualifier

        delay = 0.5
        for attempt in range(_RETRIES + 1):
            try:
                response = self._client.invoke_agent_runtime(**request)
                break
            except Exception as exc:  # noqa: BLE001 - mapped to a friendly BackendError below
                code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code")
                if code == "RetryableConflictException" and attempt < _RETRIES:
                    time.sleep(delay)  # transient: the session is being started or torn down
                    delay *= 2
                    continue
                raise explain(exc) from exc

        stream = response["response"]
        try:
            content_type = str(response.get("contentType", ""))
            if not content_type.startswith("text/event-stream"):
                sample = stream.read(400).decode("utf-8", "replace").strip()
                raise BackendError(
                    f"This runtime did not return an AG-UI event stream (content type {content_type or 'unknown'}). "
                    "Deploy it with the AG-UI protocol (serverProtocol AGUI). "
                    f"It said: {sample[:200]!r}"
                )
            # chunk_size=1: a larger chunk makes read() wait until that many bytes arrive, which would
            # hold back a short event (a single token) until the next one shows up.
            for raw in stream.iter_lines(chunk_size=1):
                if stop.is_set():
                    return
                yield raw.decode("utf-8", "replace")
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001 - a read error mid-stream
            raise explain(exc) from exc
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()
