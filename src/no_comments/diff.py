import os
import re
import subprocess
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
_DIFF = (
    "-c",
    "core.quotepath=off",
    "diff",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-relative",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "-M",
    "-U0",
)

Refs = tuple[str, str]


class GitError(Exception):
    pass


@dataclass
class FileDiff:
    old_path: str | None
    added: set[int] = field(default_factory=set)


def diff_range() -> Refs | None:
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        return from_ref, to_ref
    return None


def _git_bytes(*args: str) -> bytes:
    try:
        proc = subprocess.run(["git", "--literal-pathspecs", *args], capture_output=True)
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(message or f"git {args[0]} failed")
    return proc.stdout


def git(*args: str) -> str:
    return _git_bytes(*args).decode("utf-8", "replace")


def unquote(path: str) -> str:
    if not path.startswith('"'):
        return path
    out = bytearray()
    i, body = 0, path[1:-1]
    while i < len(body):
        char = body[i]
        if char != "\\":
            out += char.encode("utf-8")
            i += 1
        elif body[i + 1] in "01234567":
            out.append(int(body[i + 1 : i + 4], 8))
            i += 4
        else:
            out.append(_ESCAPES[body[i + 1]])
            i += 2
    return out.decode("utf-8", "replace")


def _header_path(raw: str, prefix: str) -> str | None:
    path = unquote(raw) if raw.startswith('"') else raw.removesuffix("\t")
    if path == "/dev/null":
        return None
    return path.removeprefix(prefix)


def _hunk_lines(line: str) -> range:
    match = _HUNK.match(line)
    if not match:
        return range(0)
    start = int(match.group(1))
    count = 1 if match.group(2) is None else int(match.group(2))
    return range(start, start + count)


def parse_diff(text: str) -> dict[str, FileDiff]:
    files: dict[str, FileDiff] = {}
    current: FileDiff | None = None
    in_header = False
    old: str | None = None
    new: str | None = None
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            current, in_header, old, new = None, True, None, None
        elif in_header and line.startswith("rename from "):
            old = unquote(line.removeprefix("rename from "))
        elif in_header and line.startswith("--- "):
            old = old or _header_path(line[4:], "a/")
        elif in_header and line.startswith("+++ "):
            new = _header_path(line[4:], "b/")
        elif line.startswith("@@"):
            if in_header:
                in_header = False
                current = None if new is None else files.setdefault(new, FileDiff(old))
            if current is not None:
                current.added.update(_hunk_lines(line))
    return files


def collect_changes(refs: Refs | None) -> dict[str, FileDiff]:
    target = "--cached" if refs is None else f"{refs[0]}...{refs[1]}"
    return parse_diff(git(*_DIFF, target))


def _is_commit(rev: str) -> bool:
    try:
        git("rev-parse", "-q", "--verify", f"{rev}^{{commit}}")
    except GitError:
        return False
    return True


def base_revisions(refs: Refs | None) -> list[str]:
    if refs is not None:
        return [git("merge-base", *refs).strip()]
    if not _is_commit("HEAD"):
        return []
    return ["HEAD", "MERGE_HEAD"] if _is_commit("MERGE_HEAD") else ["HEAD"]


def read_blob(rev: str, path: str) -> str | None:
    try:
        return _git_bytes("cat-file", "blob", f"{rev}:{path}").decode("utf-8-sig")
    except (GitError, UnicodeDecodeError):
        return None
