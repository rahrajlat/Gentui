"""Gentui's identity: logo mark, wordmarks, colours and the animations built from them."""

import time

from rich.text import Text

MARK = "◈"  # the logo mark: a diamond within a diamond
USER_MARK = "❯"
TOOL_MARK = "◇"
RESULT_MARK = "└"
TAGLINE = "generative UI for your terminal"

SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"  # braille dots
GRADIENT = ("#4FD6C8", "#A78BFA")  # teal -> violet
HIGHLIGHT = "#FFFFFF"

WORDMARK_BIG = """\
 ██████╗ ███████╗███╗   ██╗████████╗██╗   ██╗██╗
██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██║   ██║██║
██║  ███╗█████╗  ██╔██╗ ██║   ██║   ██║   ██║██║
██║   ██║██╔══╝  ██║╚██╗██║   ██║   ██║   ██║██║
╚██████╔╝███████╗██║ ╚████║   ██║   ╚██████╔╝██║
 ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝"""

WORDMARK_SMALL = """\
┏━╸┏━╸┏┓╻╺┳╸╻ ╻╻
┃╺┓┣╸ ┃┗┫ ┃ ┃ ┃┃
┗━┛┗━╸╹ ╹ ╹ ┗━┛╹"""


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def blend(a: str, b: str, t: float) -> str:
    """Mix two #rrggbb colours; t=0 gives a, t=1 gives b."""
    t = max(0.0, min(1.0, t))
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    return f"#{round(r1 + (r2 - r1) * t):02x}{round(g1 + (g2 - g1) * t):02x}{round(b1 + (b2 - b1) * t):02x}"


def gradient_color(position: float) -> str:
    return blend(GRADIENT[0], GRADIENT[1], position)


def wordmark_for(width: int) -> str:
    big_width = max(len(line) for line in WORDMARK_BIG.splitlines())
    return WORDMARK_BIG if width >= big_width + 4 else WORDMARK_SMALL


def logo_static(wordmark: str) -> Text:
    """The finished logo: the full wordmark in its gradient, with no animation."""
    return logo_frame(wordmark, t=1e6, sweep=False)


def logo_frame(wordmark: str, t: float, reveal_seconds: float = 0.9, sweep: bool = True) -> Text:
    """The wordmark at time `t` seconds: first revealed left to right, then a highlight sweeps over it."""
    lines = wordmark.splitlines()
    width = max(len(line) for line in lines)
    shown = int(width * min(1.0, t / reveal_seconds))
    light = ((t - reveal_seconds) * 55) % (width + 24) - 12 if sweep and t > reveal_seconds else -99
    text = Text(no_wrap=True)
    for row, line in enumerate(lines):
        for col, ch in enumerate(line.ljust(width)):
            if ch == " " or col >= shown:
                text.append(" ")
                continue
            color = gradient_color(col / max(1, width - 1))
            glow = max(0.0, 1 - abs(col - light - row) / 6)  # slanted band of light
            text.append(ch, style=f"bold {blend(color, HIGHLIGHT, glow * 0.7)}")
        if row < len(lines) - 1:
            text.append("\n")
    return text


def thinking_label(elapsed: float, now: float | None = None) -> Text:
    """'⣾ Thinking… (4s)': a braille spinner and a light that sweeps across the word."""
    now = time.monotonic() if now is None else now
    word = "Thinking…"
    sweep = (now * 9) % (len(word) + 6) - 3
    text = Text()
    text.append(SPINNER[int(now * 12) % len(SPINNER)] + " ", style=f"bold {GRADIENT[0]}")
    for i, ch in enumerate(word):
        glow = max(0.0, 1 - abs(i - sweep) / 3)
        text.append(ch, style=blend(GRADIENT[1], HIGHLIGHT, glow))
    text.append(f" ({int(elapsed)}s)", style="dim")
    return text
