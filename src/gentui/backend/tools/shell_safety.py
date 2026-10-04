"""Safety rules for shell commands. Pure functions, easy to test.

`check_command` returns a reason string if the command must be refused, else None.
It is enforced twice: when a command is proposed and again right before execution,
so an approval can never override it.

This is a denylist: a safety net against obvious disasters, NOT a sandbox.
The human approval step is the real protection.
"""

import re

_FLAGS = re.IGNORECASE

# (reason, regex). Order doesn't matter; first match wins.
_DANGEROUS: list[tuple[str, re.Pattern[str]]] = [
    (
        "recursive delete of a root, home or drive-level path",
        re.compile(
            r"\brm\b[^;&|\n]*\s-[a-z]*r[a-z]*[^;&|\n]*\s(/|/\*|~/?|~/\*|\$HOME/?|\*)(\s|$)"
            r"|\brm\b[^;&|\n]*--no-preserve-root"
            r"|\b(remove-item|ri|rd|rmdir|del|erase)\b(?=[^;&|\n]*(-recurse|\s/s\b))[^;&|\n]*"
            r"\s['\"]?([a-z]:\\?|\\|~|\$HOME|\$env:(userprofile|homepath)|c:\\users\\?)['\"]?(\s|$)",
            _FLAGS,
        ),
    ),
    (
        "disk formatting or raw disk writes",
        re.compile(
            r"\bmkfs(\.\w+)?\b|\bformat-volume\b|\bclear-disk\b|\bdiskpart\b|\bfdisk\b"
            r"|\bformat\s+[a-z]:|\bdd\b[^;&|\n]*\bof=/dev/|>\s*/dev/(sd|nvme|hd|disk)",
            _FLAGS,
        ),
    ),
    (
        "shutdown or reboot",
        re.compile(
            # only in command position, so `echo shutdown` is fine
            r"(^|[;&|(]|\bsudo)\s*(shutdown|reboot|poweroff|halt|stop-computer|restart-computer)\b"
            r"|(^|[;&|(]|\bsudo)\s*init\s+[06]\b",
            _FLAGS,
        ),
    ),
    (
        "registry edit",
        re.compile(
            r"\breg(\.exe)?\s+(add|delete|import|load|unload)\b|\bregedit\b"
            r"|\b(set|new|remove)-itemproperty\b[^;&|\n]*\bhk(lm|cu|cr|u|cc)\b"
            r"|\bremove-item\b[^;&|\n]*\bhk(lm|cu|cr|u|cc):",
            _FLAGS,
        ),
    ),
    ("fork bomb", re.compile(r":\(\)\s*\{.*\};\s*:")),
    (
        "recursive permission change on the filesystem root",
        re.compile(r"\b(chmod|chown)\b[^;&|\n]*\s-[a-z]*r[a-z]*[^;&|\n]*\s/(\s|$)", _FLAGS),
    ),
]

_INTERACTIVE = re.compile(
    r"^\s*(sudo\s+)?(vim?|nano|emacs|less|more|top|htop|man|pico|watch)(\s|$)", _FLAGS
)


def check_command(command: str) -> str | None:
    """Reason to refuse `command`, or None if it may be proposed/run (after approval)."""
    if not command.strip():
        return "empty command"
    for reason, pattern in _DANGEROUS:
        if pattern.search(command):
            return f"blocked by safety policy: {reason}"
    if _INTERACTIVE.search(command):
        return "interactive programs are not supported (no editors, pagers or live viewers)"
    return None
