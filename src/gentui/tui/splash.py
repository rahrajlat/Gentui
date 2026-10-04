"""Startup splash: the wordmark is revealed with a gradient, a light sweeps over it, then the tagline types out."""

import time

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Click, Key
from textual.screen import Screen
from textual.widgets import Static

from gentui.tui import branding


class SplashScreen(Screen[None]):
    """Closes itself after `duration` seconds, or on any key or click."""

    DEFAULT_CSS = """
    SplashScreen { align: center middle; background: $background; }
    SplashScreen Vertical { width: auto; height: auto; align-horizontal: center; }
    #logo { width: auto; height: auto; }
    #tagline { width: auto; margin-top: 1; color: $text-muted; }
    #skip { width: auto; margin-top: 2; color: $text-muted 50%; }
    """

    def __init__(self, duration: float = 2.4, version: str = "") -> None:
        super().__init__()
        self.duration = duration
        self.version = version
        self._t0 = 0.0
        self._wordmark = branding.WORDMARK_SMALL

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="logo")
            yield Static(id="tagline")
            yield Static("press any key", id="skip")

    def on_mount(self) -> None:
        self._wordmark = branding.wordmark_for(self.app.size.width)
        self._t0 = time.monotonic()
        self.set_interval(1 / 30, self._frame)
        self._frame()

    def _frame(self) -> None:
        t = time.monotonic() - self._t0
        self.query_one("#logo", Static).update(branding.logo_frame(self._wordmark, t))
        typed = int(max(0.0, t - 0.8) * 45)
        tagline = f"{branding.MARK}  {branding.TAGLINE}"
        self.query_one("#tagline", Static).update(Text(tagline[:typed].ljust(len(tagline))))
        if t >= self.duration:
            self.dismiss()

    def on_key(self, event: Key) -> None:
        event.stop()
        self.dismiss()

    def on_click(self, event: Click) -> None:
        event.stop()
        self.dismiss()
