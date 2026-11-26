import re
from collections.abc import Sequence

from no_comments.langs import Comment, Kind, typescript

COMMON_PREFIXES = ("KEEP:", "SPDX-License-Identifier:")
PYTHON_PREFIXES = (
    "noqa",
    "type:",
    "pyright:",
    "ty:",
    "mypy:",
    "pragma:",
    "fmt:",
    "isort:",
    "ruff:",
    "pylint:",
)
SHELL_PREFIXES = ("shellcheck",)
_CODING = re.compile(r"coding[:=]")
_TRAILING_HASH = re.compile(r"\s#")


def is_allowed(lang: str, comment: Comment, extra: Sequence[re.Pattern[str]] = ()) -> bool:
    text = comment.body
    if comment.kind is Kind.DOCSTRING:
        return text.startswith("KEEP:") or any(pattern.search(text) for pattern in extra)
    if comment.line == 1 and comment.col == 1 and comment.text.startswith("#!"):
        return True
    if text.startswith(COMMON_PREFIXES):
        return True
    if lang == "python" and comment.line <= 2 and _CODING.search(text):
        return True
    if lang in {"typescript", "tsx"} and typescript.is_directive(comment):
        return True
    tool_prefixes = {"python": PYTHON_PREFIXES, "shell": SHELL_PREFIXES}.get(lang, ())
    if text.startswith(tool_prefixes) and not _TRAILING_HASH.search(text):
        return True
    return any(pattern.search(text) for pattern in extra)
