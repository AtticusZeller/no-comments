import os
import re
import subprocess

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

Refs = tuple[str, str]


class GitError(Exception):
    pass


def diff_range() -> Refs | None:
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        return from_ref, to_ref
    return None


def parse_added_lines(diff_text: str) -> set[int]:
    added: set[int] = set()
    for line in diff_text.splitlines():
        match = _HUNK.match(line)
        if match:
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            added.update(range(start, start + count))
    return added


def git(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "--literal-pathspecs", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {args[0]} failed")
    return proc.stdout


def added_lines(path: str, refs: Refs | None) -> set[int]:
    target = ["--cached"] if refs is None else [f"{refs[0]}...{refs[1]}"]
    out = git("diff", "--no-ext-diff", "--no-color", "-U0", *target, "--", path)
    return parse_added_lines(out)
