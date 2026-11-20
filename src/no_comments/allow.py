import re
from collections.abc import Sequence

from no_comments.langs import Comment

COMMON_PREFIXES = ("KEEP:", "SPDX-License-Identifier:")
PYTHON_PREFIXES = (
    "noqa",
    "type:",
    "pyright:",
    "mypy:",
    "pragma:",
    "fmt:",
    "isort:",
    "ruff:",
    "pylint:",
)
SHELL_PREFIXES = ("shellcheck",)
_CODING = re.compile(r"coding[:=]")


def body(text: str) -> str:
    return text.lstrip("#").lstrip()


def is_allowed(lang: str, comment: Comment, extra: Sequence[re.Pattern[str]] = ()) -> bool:
    if comment.line == 1 and comment.col == 1 and comment.text.startswith("#!"):
        return True
    text = body(comment.text)
    if text.startswith(COMMON_PREFIXES):
        return True
    if lang == "python":
        if comment.line <= 2 and _CODING.search(text):
            return True
        if text.startswith(PYTHON_PREFIXES):
            return True
    if lang == "shell" and text.startswith(SHELL_PREFIXES):
        return True
    return any(pattern.search(text) for pattern in extra)
