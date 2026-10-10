"""The docs name every flag the CLI has, and the MkDocs nav only lists pages that exist."""

import re
from pathlib import Path

from gentui import cli

ROOT = Path(__file__).parent.parent


def flags() -> set[str]:
    source = Path(cli.__file__).read_text()
    return {f for f in re.findall(r'"(--[a-z][a-z-]*)"', source) if f != "--help"}


def test_every_cli_flag_is_in_the_reference():
    reference = (ROOT / "docs" / "cli.md").read_text()
    missing = sorted(f for f in flags() if f"`{f}" not in reference)
    assert not missing, f"docs/cli.md does not mention {missing}"


def test_every_nav_page_exists():
    nav = (ROOT / "mkdocs.yml").read_text()
    pages = re.findall(r":\s+([\w-]+\.md)\s*$", nav, re.M)
    assert pages and all((ROOT / "docs" / page).is_file() for page in pages)
