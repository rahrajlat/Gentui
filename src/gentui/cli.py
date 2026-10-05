"""`gentui` command: point it at any AG-UI backend and go."""

import argparse
import sys

from gentui.config import load_config


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
    parser.add_argument("--no-reasoning", action="store_true", help="hide the model's chain of thought")
    parser.add_argument("--dev", action="store_true", help="open the AG-UI event inspector at start")
    args = parser.parse_args(argv)

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
                "    uv sync --extra agentcore        (from a clone)\n"
                "    pip install 'gentui[agentcore]'   (from PyPI, once published)"
            )
        except (BackendError, ValueError) as exc:
            sys.exit(f"gentui: {exc}")
    else:
        client = AguiClient(config.url, config.request_headers, config.timeout, config.send_history)
    GentuiApp(client, config).run()


if __name__ == "__main__":
    main()
