"""`gentui` command: point it at any AG-UI backend and go."""

import argparse
import sys
from pathlib import Path

from gentui.config import load_config


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("gentui")
    except PackageNotFoundError:  # running from a source tree that is not installed
        return "unknown"


def parse_headers(items: list[str] | None) -> dict[str, str] | None:
    if not items:
        return None
    headers = {}
    for item in items:
        key, sep, value = item.partition(":")
        if not sep:
            raise SystemExit(f"--header expects 'Name: value', got {item!r}")
        headers[key.strip()] = value.strip()
    return headers


def _run(app, record: str | None, prompts: list[str] | None = None) -> None:
    """Run the app, saving the session when --record was given and sending the --prompts."""
    app.queued_prompts = prompts or []
    if record:
        from gentui.session import Recorder, SessionError, resolve

        try:
            app.recorder = Recorder(resolve(record), app.config.target)
        except SessionError as exc:
            sys.exit(f"gentui: {exc}")
    app.run()
    if app.recorder:
        print(f"Saved the session to {app.recorder.path}. Play it back with: gentui --replay {app.recorder.path.stem}")


def _run_replay(name: str, config) -> None:
    from gentui.session import SessionError, load, resolve
    from gentui.tui.replay import ReplayApp

    try:
        session = load(resolve(name))
    except SessionError as exc:
        sys.exit(f"gentui: {exc}")
    ReplayApp(session, config).run()


def _run_compare(parser: argparse.ArgumentParser, names: str, config) -> None:
    from gentui.session import SessionError, load, resolve
    from gentui.tui.compare import CompareApp

    wanted = [name.strip() for name in names.split(",") if name.strip()]
    if len(wanted) < 2:
        parser.error("--compare needs at least two recorded sessions, e.g. --compare before,after")
    try:
        sessions = [load(resolve(name)) for name in wanted]
    except SessionError as exc:
        sys.exit(f"gentui: {exc}")
    CompareApp(sessions, config).run()


def _run_demo(parser: argparse.ArgumentParser, args: argparse.Namespace, config) -> None:
    from gentui.tui import demo

    scene = demo.choose_scene() if args.demo == "menu" else args.demo
    if scene not in demo.SCENES:
        parser.error(f"unknown demo scene {scene!r}; choose from:\n{demo.scene_list()}")
    config.agentcore_arn, config.url = None, "demo mode (scripted, no backend)"
    config.welcome = (
        "◈ Welcome to Gentui! This is the demo: sit back, it plays by itself.\n\n"
        "  /demo to pick a scene · /help for commands · /quit to exit\n  backend: {url}"
    )
    _run(demo.DemoApp(demo.DemoClient(args.demo_speed), config, scene), args.record)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="gentui",
        description="Terminal client for any AG-UI agent backend.",
        epilog="Options can also live in gentui.toml (see gentui.example.toml).",
    )
    parser.add_argument(
        "url_pos", nargs="?", metavar="URL|ARN",
        help="AG-UI endpoint, or an AgentCore runtime ARN (same as --url / --agentcore-arn)",
    )
    parser.add_argument("--url", help="AG-UI endpoint [default: http://localhost:8000/agent]")
    parser.add_argument("--agentcore-arn", metavar="ARN", help="agent on Amazon Bedrock AgentCore Runtime (AG-UI protocol)")
    parser.add_argument("--region", help="AWS region for AgentCore [default: the region in the ARN]")
    parser.add_argument("--profile", help="AWS profile for AgentCore [default: the standard credential chain]")
    parser.add_argument("--qualifier", help="AgentCore runtime endpoint name [default: DEFAULT]")
    parser.add_argument("--token", help="send 'Authorization: Bearer <token>' (or set GENTUI_TOKEN)")
    parser.add_argument("--header", "-H", action="append", metavar="'Name: value'", help="extra HTTP header (repeatable)")
    parser.add_argument("--config", "-c", metavar="FILE", help="config file [default: ./gentui.toml]")
    parser.add_argument("--theme", help="Textual theme name")
    parser.add_argument("--css", metavar="FILE", help="your own CSS file (hot-reloaded)")
    parser.add_argument("--plugin", "-p", action="append", metavar="MODULE|FILE", help="load a plugin (repeatable)")
    parser.add_argument("--version", action="version", version=f"gentui {_version()}")
    parser.add_argument("--no-reasoning", action="store_true", help="hide the model's chain of thought")
    parser.add_argument(
        "--demo", nargs="?", const="menu", metavar="SCENE",
        help="play a scripted tour, no backend needed: all, chat, approval, widgets or devtools (no name = a menu)",
    )
    parser.add_argument("--demo-speed", type=float, default=1.0, metavar="X", help="demo playback speed [default: 1]")
    parser.add_argument("--record", metavar="NAME", help="save this session to NAME.json (what you type and every event)")
    parser.add_argument("--replay", metavar="NAME", help="play back NAME.json: pause, play, seek, no backend needed")
    parser.add_argument("--prompts", metavar="FILE", help="send the prompts in this YAML file one after the other (combine with --record)")
    parser.add_argument(
        "--compare", metavar="NAME,NAME,...",
        help="compare recorded sessions side by side as a diff, picking which two from drop-downs; no backend needed",
    )
    parser.add_argument("--dev", action="store_true", help="open the AG-UI event inspector at start")
    args = parser.parse_args(argv)
    if args.demo and args.demo_speed <= 0:
        parser.error("--demo-speed must be above 0")

    if args.record and args.replay:
        parser.error("--record and --replay cannot be used together")
    if args.replay and args.demo:
        parser.error("--replay and --demo cannot be used together")

    if args.compare and (args.record or args.replay or args.demo or args.prompts):
        parser.error("--compare cannot be combined with --record, --replay, --demo or --prompts")
    if args.prompts and (args.replay or args.demo):
        parser.error("--prompts needs a live backend: it cannot be combined with --replay or --demo")
    prompts = None
    if args.prompts:
        from gentui.prompts import PromptsError, load as load_prompts

        try:
            prompts = load_prompts(Path(args.prompts))
        except PromptsError as exc:
            sys.exit(f"gentui: {exc}")

    target = args.url or args.url_pos
    arn = args.agentcore_arn or (target if target and target.startswith("arn:") else None)
    try:
        config = load_config(
            args.config,
            url=None if arn else target,
            agentcore_arn=arn,
            region=args.region,
            aws_profile=args.profile,
            qualifier=args.qualifier,
            token=args.token,
            headers=parse_headers(args.header),
            theme=args.theme,
            css=args.css,
            plugins=args.plugin,
            show_reasoning=False if args.no_reasoning else None,
            dev_pane=True if args.dev else None,
        )
    except (OSError, ValueError) as exc:
        sys.exit(f"gentui: {exc}")

    if args.compare:
        _run_compare(parser, args.compare, config)
        return
    if args.replay:
        _run_replay(args.replay, config)
        return
    if args.demo:
        _run_demo(parser, args, config)
        return

    from gentui.tui.agui_client import AguiClient, BackendError
    from gentui.tui.app import GentuiApp

    if config.agentcore_arn:
        try:
            from gentui.tui.agentcore_client import AgentCoreClient

            client = AgentCoreClient(
                config.agentcore_arn, config.region, config.aws_profile, config.qualifier,
                config.timeout, config.send_history,
            )
        except ImportError:
            sys.exit(
                "gentui: AgentCore support needs boto3. Install it with:\n"
                "    pip install 'gentui[agentcore]'\n"
                "    uv tool install 'gentui[agentcore]'\n"
                "    uv sync --extra agentcore         (from a clone)"
            )
        except (BackendError, ValueError) as exc:
            sys.exit(f"gentui: {exc}")
    else:
        client = AguiClient(config.url, config.request_headers, config.timeout, config.send_history)
    _run(GentuiApp(client, config), args.record, prompts)


if __name__ == "__main__":
    main()
