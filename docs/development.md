# Development and status

## Status

Gentui is **alpha**. What has been verified, and what has not:

- Built and tested against the **Strands Agents** framework (AWS) over AG-UI: the
  [example backend](https://github.com/rahrajlat/Gentui/tree/main/examples/strands-backend) and the official
  [`ag-ui-strands`](https://pypi.org/project/ag-ui-strands/) adapter (with `send_history = true`).
- AgentCore Runtime support works against a real runtime (confirmed by the author with a plain runtime ARN) and only
  covers runtimes using the AG-UI protocol. Other setups are covered by tests with a fake boto3 client and botocore's `Stubber`.
- Backends on other frameworks, the interrupt flow against a backend other than the example, other model
  providers than Ollama, and native Windows are **untested**.
- The look relies on Unicode box-drawing and block characters. If glyphs are missing, try a terminal
  font such as DejaVu Sans Mono, Cascadia or JetBrains Mono.

**Ideas, not built yet:** `show_form` / `ask_approval` tools, a composable JSON-tree UI tool, persistent
threads.

## Development

```bash
uv run pytest -q                                   # TUI tests: headless, no LLM or backend needed
cd examples/strands-backend && uv run pytest -q    # the example backend's own tests
```

The images above are generated from the app's own code:
`uv run --with pillow python docs/assets/build_assets.py` (logo, hero, `demo.gif`) and
`uv run --with pillow python docs/assets/build_tour.py` (the feature tour), and
`uv run --with pillow python docs/assets/build_replay.py` (the replay), and
`uv run --with pillow python docs/assets/build_compare.py` (compare and judge).

The docs site is built with MkDocs Material: `uv run --group docs mkdocs serve` previews it locally.

## Contributing

Issues and pull requests are welcome. Please run both test suites before opening a PR, and add a test
with any behaviour change. Because Gentui is a client for an open protocol, changes that keep it
backend-agnostic are the easiest to accept.

