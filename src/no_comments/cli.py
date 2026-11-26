import argparse
import codecs
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from no_comments import report
from no_comments.allow import is_allowed
from no_comments.compare import new_comments, pool, retained_comments
from no_comments.detect import (
    EXTENSIONS,
    detect_language,
    shebang_language,
    through_symlink,
)
from no_comments.diff import (
    GitError,
    base_revisions,
    collect_changes,
    diff_range,
    git,
    read_blobs,
)
from no_comments.langs import Comment, ParseError, python, shell, typescript
from no_comments.rewrite import run_strip
from no_comments.strip import run_verify_strip

EXTRACTORS: dict[str, Callable[[str], list[Comment]]] = {
    "python": python.extract,
    "shell": shell.extract,
    "typescript": typescript.extract,
    "tsx": typescript.extract_tsx,
}


def parse(source: str, lang: str) -> list[Comment]:
    return EXTRACTORS[lang](source)


def source_language(name: str, data: bytes) -> str | None:
    return EXTENSIONS.get(Path(name).suffix) or shebang_language(
        data.removeprefix(codecs.BOM_UTF8).split(b"\n", 1)[0]
    )


def load_comments(name: str, data: bytes, lang: str, *, warn: bool = True) -> list[Comment]:
    try:
        if lang == "python":
            python.require_utf8(data)
        return parse(data.decode("utf-8-sig"), lang)
    except typescript.TypeScriptParseError as exc:
        if warn:
            raise ParseError(f"{name}: {exc}") from exc
    except (ParseError, UnicodeDecodeError) as exc:
        if warn:
            print(f"no-comments: warning: skipping {name}: {exc}", file=sys.stderr)
    return []


def previous_comments(rev: str, paths: list[str]) -> dict[str, list[Comment]]:
    versions = {}
    for path, data in read_blobs(rev, paths).items():
        if (lang := source_language(path, data)) is not None:
            versions[path] = load_comments(path, data, lang, warn=False)
    return versions


def run_check(files: Sequence[str], extra: Sequence[re.Pattern[str]]) -> int:
    targets = {os.path.normpath(name): name for name in files}
    refs = diff_range()
    snapshot = refs[1] if refs else ""
    bases = base_revisions(refs)
    changes = collect_changes(
        refs, lambda path: Path(path).suffix in EXTENSIONS, shebang_revisions=[snapshot, *bases]
    )
    if not any(c.new_path in targets and c.added for c in changes):
        return 0
    blobs = read_blobs(snapshot, [c.new_path for c in changes if c.new_path is not None])
    old_paths = [c.old_path for c in changes if c.old_path is not None]
    previous = [previous_comments(rev, old_paths) for rev in bases]
    baseline = previous[0] if previous else {}
    current: dict[str, tuple[list[Comment], set[int]]] = {}
    languages: dict[str, str] = {}
    retained = set()
    for change in changes:
        path = change.new_path
        if path is None or path not in blobs:
            continue
        data = blobs[path]
        if (lang := source_language(path, data)) is None:
            continue
        languages[path] = lang
        comments = load_comments(path, data, lang, warn=path in targets and bool(change.added))
        current[path] = (comments, change.added)
        if change.old_path is not None and change.replaced:
            old = baseline.get(change.old_path, [])
            retained.update((path, c) for c in retained_comments(old, comments, change.replaced))
    violations = [
        (targets[path], comment)
        for path, comment in new_comments(current, [pool(v.values()) for v in previous], retained)
        if path in targets and not is_allowed(languages[path], comment, extra)
    ]
    if not violations:
        return 0
    report.print_violations(violations)
    report.print_hint(violations)
    return 1


def audit_files(paths: Sequence[str]) -> list[str]:
    if not paths:
        return git("ls-files", "-z").split("\0")[:-1]
    paths = [p for p in paths if not through_symlink(Path(p))]
    dirs = [p for p in paths if Path(p).is_dir()]
    listed = git("ls-files", "-z", "--", *dirs).split("\0")[:-1] if dirs else []
    return [p for p in paths if not Path(p).is_dir()] + listed


def run_audit(paths: Sequence[str], extra: Sequence[re.Pattern[str]]) -> int:
    for name in audit_files(paths):
        if through_symlink(Path(name)):
            continue
        lang = detect_language(Path(name))
        if lang is None:
            continue
        comments = load_comments(name, Path(name).read_bytes(), lang)
        report.print_violations([(name, c) for c in comments if not is_allowed(lang, c, extra)])
    return 0


def regex(value: str) -> re.Pattern[str]:
    try:
        return re.compile(value)
    except re.error as exc:
        raise argparse.ArgumentTypeError(f"invalid regex {value!r}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--allow", action="append", type=regex, default=[], metavar="REGEX")
    parser = argparse.ArgumentParser(prog="no-comments")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", parents=[common], help="report comments on added lines")
    check.add_argument("files", nargs="*", metavar="FILE")
    audit = sub.add_parser("audit", parents=[common], help="list every comment in the given paths")
    audit.add_argument("paths", nargs="*", metavar="PATH")
    strip = sub.add_parser("strip", help="apply DELETE and KEEP from a reviewed audit")
    strip.add_argument("review", type=Path, metavar="REVIEW")
    strip.add_argument("--audit", required=True, type=Path, metavar="FILE", help="saved audit output")
    verify_strip = sub.add_parser(
        "verify-strip", help="fail if the working tree differs from REF beyond comments"
    )
    verify_strip.add_argument("--base", default="HEAD", metavar="REF")
    verify_strip.add_argument("files", nargs="*", metavar="FILE")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check":
            return run_check(args.files, args.allow)
        if args.command == "verify-strip":
            return run_verify_strip(args.base, args.files)
        if args.command == "strip":
            return run_strip(args.review, args.audit)
        return run_audit(args.paths, args.allow)
    except (GitError, ParseError, OSError, UnicodeDecodeError) as exc:
        print(f"no-comments: error: {exc}", file=sys.stderr)
        return 2
