# Agents on Amazon Bedrock AgentCore Runtime

Gentui can talk to an agent hosted on [Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html),
invoking it with boto3's [`invoke_agent_runtime`](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html).
Your normal AWS credentials are used and requests are signed with SigV4, so there is no URL or token to manage.

## What is supported

**Runtimes deployed with the AG-UI protocol** (`serverProtocol: AGUI`). Such a runtime accepts a standard
AG-UI `RunAgentInput` at `/invocations` and answers with an SSE stream of AG-UI events, which is exactly what
Gentui already speaks. See AWS's
[AG-UI protocol contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-agui-protocol-contract.html).

**Not supported:** runtimes using the plain HTTP protocol (a custom payload and a custom stream), MCP or A2A.
They do not speak AG-UI. If you point Gentui at one, it tells you so (see Troubleshooting).

## Install

boto3 is an optional dependency, so everyone else keeps the small install:

```bash
uv sync --extra agentcore            # from a clone
pip install 'gentui[agentcore]'      # from PyPI, once it is published
```

## Run

```bash
uv run gentui arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my_agent-AbCdEfGhIj
uv run gentui --agentcore-arn ARN --profile dev --region eu-west-1 --qualifier prod
```

Or in `gentui.toml` (see [gentui.example.toml](../gentui.example.toml)):

```toml
agentcore_arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my_agent-AbCdEfGhIj"
# region = "us-east-1"       # default: the region in the ARN
# aws_profile = "dev"        # default: the standard AWS credential chain
# qualifier = "prod"         # default: the runtime's DEFAULT endpoint
```

`GENTUI_AGENTCORE_ARN` works too. When an ARN is set, `url` is ignored.

**Endpoint ARNs are accepted too.** An ARN ending in `/runtime-endpoint/<name>` (for example
`.../runtime/my_agent-AbCdEfGhIj/runtime-endpoint/DEFAULT`) is split for you: the API is called with the plain runtime ARN and
the endpoint name as the `qualifier`. If you also pass `--qualifier` it must match the endpoint in the ARN.

## AWS setup

- **Credentials:** anything boto3 finds: `AWS_PROFILE`, `aws sso login`, environment variables, an instance role.
- **Permission:** the caller needs `bedrock-agentcore:InvokeAgentRuntime` on the runtime (and
  `bedrock-agentcore:InvokeAgentRuntimeForUser` if you use user ids).
- **A runtime that speaks AG-UI:** deploy your agent with the AG-UI protocol. For Strands agents, the
  [`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter is one way to serve it.

## How it behaves

| Topic | Behaviour |
|---|---|
| Request | A `RunAgentInput` JSON payload, `contentType: application/json`, `accept: text/event-stream` |
| Sessions | One Gentui conversation is one AgentCore runtime session. The id is stable per thread (`gentui-<thread id>`, always 33 to 256 characters as the API requires), so a runtime that keeps state per session keeps it for the whole chat. `/clear` starts a new thread and therefore a new session |
| History | Same as any backend: only the newest message is sent. A runtime that rebuilds context from the message list (the `ag-ui-strands` adapter does) needs `send_history = true` |
| Streaming | Events are shown as they arrive. The stream is read one byte at a time on purpose, so a short event is not held back until the next one arrives |
| Timeouts | No read timeout by default (agents can think for a long time); `timeout = <seconds>` sets one |
| Busy session | `RetryableConflictException` ("session busy") is retried up to 3 times with 0.5s, 1s, 2s backoff, as AWS recommends for AG-UI clients |
| Event inspector | `d` shows the raw SSE payloads exactly as the runtime sent them |
| Interrupts / approval | Work as with any AG-UI backend: the run ends with an interrupt and your click `resume`s it on the same session |

## Runtimes that use OAuth (JWT) inbound auth

boto3 signs requests with SigV4, which a runtime configured for OAuth will refuse. For those, call the runtime's HTTPS
endpoint with the normal URL mode, as AWS documents: a bearer token plus a session id header.

```bash
uv run gentui "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<URL-ENCODED-ARN>/invocations?qualifier=DEFAULT" \
  --token "$ACCESS_TOKEN" -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: <a session id of 33+ characters>"
```

The session id header is fixed for the process in this mode. This path is **untested**.

## Troubleshooting

| You see | Likely cause |
|---|---|
| `No AWS credentials found` | Run `aws sso login`, set `AWS_PROFILE`, or pass `--profile` |
| `Your AWS credentials were rejected` | Expired or wrong credentials; refresh them |
| `Access denied. The caller needs bedrock-agentcore:InvokeAgentRuntime` | Add that IAM permission for the runtime |
| `Runtime not found` | Wrong ARN, region or `--qualifier` |
| `not an AgentCore runtime ARN` | The ARN is malformed. Use `arn:aws:bedrock-agentcore:<region>:<account>:runtime/<name>`, optionally followed by `/runtime-endpoint/<endpoint>` |
| `the ARN names endpoint ... but --qualifier is ...` | The ARN and `--qualifier` disagree. Use only one |
| `This runtime did not return an AG-UI event stream` | The runtime uses the HTTP protocol (or returns JSON). Deploy it with the AG-UI protocol |
| `The agent code failed while running` | Your agent raised an error; check the runtime's CloudWatch logs |
| `AgentCore support needs boto3` | `uv sync --extra agentcore` |

## Status

The author has run this against a real AgentCore runtime with a plain runtime ARN, and it works. The endpoint-ARN form
was added afterwards and is covered by tests only: a fake boto3 client (with botocore's real streaming body) and botocore's
`Stubber`, which checks the request against AWS's service model. If you try other setups, please open an issue with what you see.
