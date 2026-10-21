# Getting started

Requires Python 3.12 or newer. Gentui is on [PyPI](https://pypi.org/project/gentui/):

```bash
pip install gentui                               # or: uv tool install gentui
gentui http://localhost:8000/agent               # your AG-UI endpoint
```

With [uv](https://docs.astral.sh/uv/) you can also run it without installing: `uvx gentui http://localhost:8000/agent`.

No backend yet? Run the [sample natural-language-to-shell agent](sample-agent.md)
(Strands Agents + FastAPI). It lives in this repository, so clone it first, then start the backend in one terminal. It
uses a local [Ollama](https://ollama.com) by default; see its [README](https://github.com/rahrajlat/Gentui/blob/main/examples/strands-backend/README.md) for other providers:

```bash
git clone https://github.com/rahrajlat/Gentui.git
cd Gentui/examples/strands-backend
uv sync && cp .env.example .env
uv run server                                     # http://localhost:8000/agent
```

Then, in another terminal, start Gentui as above (`gentui http://localhost:8000/agent`).


Type `/help` to list the slash commands (`/new`, `/export_md`, `/theme`, `/dev`, `/reasoning`, `/quit`).
Working on Gentui itself? Run it from a clone with `uv sync` and `uv run gentui <url>`.

## Try the demo

No backend needed. Gentui plays a tour of every feature by itself, like a movie:

```bash
gentui --demo                # a menu: pick what to watch
gentui --demo all            # the whole movie
gentui --demo approval       # one scene: chat, approval, widgets or devtools
gentui --demo all --demo-speed 2    # twice as fast
```

Inside the demo, `/demo <scene>` switches scene and `/quit` leaves. Nothing is sent anywhere.

## Run your agent without a server

If your agent is a Strands or LangChain / LangGraph agent in Python, Gentui can run it in the same process: no endpoint,
no FastAPI. See [Native Strands agents](strands-native.md) and [Native LangChain agents](langchain-native.md).

```python
from gentui import GentUI

GentUI.from_strands(agent).run()       # pip install 'gentui[strands]'
GentUI.from_langchain(agent).run()     # pip install 'gentui[langchain]'
```

## Open it in a browser

`pip install 'gentui[web]'`, then add `--serve` to any command: `gentui http://localhost:8000/agent --serve`. See the
[command-line reference](cli.md#in-the-browser).
