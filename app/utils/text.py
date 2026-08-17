"""Small text helpers shared across the app."""

from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Remove terminal colour codes.

    yt-dlp colourises its error messages, and those escape sequences end up in
    exception strings — which we show in the browser, where they render as
    literal garbage like `[0;31mERROR:[0m`.
    """
    return _ANSI_RE.sub("", str(text))
