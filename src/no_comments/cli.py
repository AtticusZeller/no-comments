import argparse
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from no_comments import report
from no_comments.allow import is_allowed
from no_comments.diff import GitError, added_lines, diff_range, git
from no_comments.langs import Comment, ParseError, python, shell

EXTENSIONS = {".py": "python", ".pyi": "python", ".sh": "shell", ".bash": "shell"}
SHELL_INTERPRETERS = {"sh", "bash", "dash", "ksh", "ash"}
EXTRACTORS: dict[str, Callable[[str], list[Comment]]] = {
    "python": python.extract,
    "shell": shell.extract,
}
_PYTHON_INTERPRETER = re.compile(r"python[0-9.]*")


def shebang_language(path: Path) -> str | None:
    with path.open("rb") as handle:
        first = handle.readline(512)
    if not first.startswith(b"#!"):
        return None
    words = first[2:].decode("utf-8", "replace").split()
    if words and os.path.basename(words[0]) == "env":
        words = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
    if not words:
        return None
    interpreter = os.path.basename(words[0])
    if _PYTHON_INTERPRETER.fullmatch(interpreter):
        return "python"
    if interpreter in SHELL_INTERPRETERS:
        return "shell"
    return None


def detect_language(path: Path) -> str | None:
    if not path.is_file():
        return None
    if path.suffix:
        return EXTENSIONS.get(path.suffix)
    return shebang_language(path)


def load_comments(path: Path, lang: str) -> list[Comment]:
    try:
        source = path.read_bytes().decode("utf-8-sig")
        return EXTRACTORS[lang](source)
    except (ParseError, UnicodeDecodeError) as exc:
        print(f"no-comments: warning: skipping {path}: {exc}", file=sys.stderr)
        return []


def run_check(files: Sequence[str], extra: Sequence[re.Pattern[str]]) -> int:
    refs = diff_range()
    violations: list[tuple[str, Comment]] = []
    for name in files:
        lang = detect_language(Path(name))
        if lang is None:
            continue
        lines = added_lines(name, refs)
        if not lines:
            continue
        violations += [
            (name, c)
            for c in load_comments(Path(name), lang)
            if c.line in lines and not is_allowed(lang, c, extra)
        ]
    if not violations:
        return 0
    report.print_violations(violations)
    report.print_hint()
    return 1


def audit_files(paths: Sequence[str]) -> list[str]:
    if not paths:
        return git("ls-files", "-z").split("\0")[:-1]
    dirs = [p for p in paths if Path(p).is_dir()]
    listed = git("ls-files", "-z", "--", *dirs).split("\0")[:-1] if dirs else []
    return [p for p in paths if not Path(p).is_dir()] + listed


def run_audit(paths: Sequence[str]) -> int:
    for name in audit_files(paths):
        lang = detect_language(Path(name))
        if lang is None:
            continue
        report.print_violations(
            (name, c) for c in load_comments(Path(name), lang) if not is_allowed(lang, c)
        )
    return 0


def regex(value: str) -> re.Pattern[str]:
    try:
        return re.compile(value)
    except re.error as exc:
        raise argparse.ArgumentTypeError(f"invalid regex {value!r}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="no-comments")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="report comments on added lines")
    check.add_argument("--allow", action="append", type=regex, default=[], metavar="REGEX")
    check.add_argument("files", nargs="*", metavar="FILE")
    audit = sub.add_parser("audit", help="list every comment in the given paths")
    audit.add_argument("paths", nargs="*", metavar="PATH")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return run_check(args.files, args.allow)
        return run_audit(args.paths)
    except GitError as exc:
        print(f"no-comments: error: {exc}", file=sys.stderr)
        return 2
