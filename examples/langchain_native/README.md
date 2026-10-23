# Native LangChain examples

Each file builds a LangChain agent (`langchain.agents.create_agent`) and opens Gentui on it, in the same process:
no server, no HTTP. `GentUI.from_langchain(agent)` works with any compiled LangGraph graph.

```bash
# from a clone:
uv sync --extra langchain --extra langchain-ollama   # adds the Ollama model provider
# or: pip install 'gentui[langchain,langchain-ollama]'
uv run python examples/langchain_native/tool_call.py
```

| File | Shows |
|---|---|
| `tool_call.py` | a tool: arguments, running, result |
| `tool_call_approval.py` | a tool that waits for Approve / Reject (`approval_middleware`) |
| `chart.py` | a terminal chart drawn from a `show_chart` call |

They pass `reasoning=True` so Ollama returns the model's thinking and Gentui can show it. They use an Ollama model (`ollama:gpt-oss:120b-cloud`): Ollama must be running and signed in for that cloud model.
Change the `init_chat_model(...)` string to use another provider (install its `langchain-*` package).

Conversation memory is LangGraph's checkpointer; if your graph has none, Gentui gives it an in-memory one, and `/new`
starts a fresh thread.
