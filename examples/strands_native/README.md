# Native Strands examples

Each file builds a Strands agent with the [Strands harness SDK](https://pypi.org/project/strands-harness/)
(`create_harness`) and opens Gentui on it, in the same process: no server, no HTTP.

```bash
uv sync --extra strands --extra harness --extra ollama     # from a clone
# or: pip install 'gentui[strands,harness,ollama]'
uv run python examples/strands_native/tool_call.py
```

| File | Shows |
|---|---|
| `tool_call.py` | a tool: arguments, running, result |
| `tool_call_approval.py` | a tool that waits for Approve / Reject |
| `chart.py` | a terminal chart drawn from a `show_chart` call |

They use an Ollama model (`ollama/gpt-oss:120b-cloud`): Ollama must be running and signed in for that cloud model.
Change the `model=` string to use another one.
