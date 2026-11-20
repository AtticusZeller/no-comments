import os
import re
import subprocess
from collections.abc import Callable
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
    "-M",
)
_MAX_PATHSPEC_BYTES = 100_000

Refs = tuple[str, str]


class GitError(Exception):
    pass


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    added: set[int] = field(default_factory=set)


def diff_range() -> Refs | None:
    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if from_ref and to_ref:
        return from_ref, to_ref
    return None


def _git_bytes(*args: str, stdin: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "--literal-pathspecs", *args], input=stdin, capture_output=True
        )
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


def parse_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
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
                current = FileDiff(old, new)
                files.append(current)
            if current is not None and current.new_path is not None:
                current.added.update(_hunk_lines(line))
    return files


def changed_paths(target: str) -> list[tuple[str | None, str | None]]:
    fields = git(*_DIFF, "--name-status", "-z", target).split("\0")
    entries: list[tuple[str | None, str | None]] = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i][0]
        if status in "RC":
            entries.append((fields[i + 1], fields[i + 2]))
            i += 3
            continue
        path = fields[i + 1]
        entries.append((None if status == "A" else path, None if status == "D" else path))
        i += 2
    return entries


def collect_changes(
    refs: Refs | None, relevant: Callable[[str], bool] = lambda _: True
) -> list[FileDiff]:
    target = "--cached" if refs is None else f"{refs[0]}...{refs[1]}"
    paths = sorted(
        {
            path
            for pair in changed_paths(target)
            if any(relevant(p) for p in pair if p is not None)
            for path in pair
            if path is not None
        }
    )
    if not paths:
        return []
    fits = sum(len(p.encode("utf-8")) + 1 for p in paths) < _MAX_PATHSPEC_BYTES
    pathspec = ["--", *paths] if fits else []
    return parse_diff(git(*_DIFF, "--src-prefix=a/", "--dst-prefix=b/", "-U0", target, *pathspec))


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


def read_blobs(rev: str, paths: list[str]) -> dict[str, str]:
    paths = [p for p in paths if "\n" not in p]
    if not paths:
        return {}
    out = _git_bytes("cat-file", "--batch", stdin="".join(f"{rev}:{p}\n" for p in paths).encode())
    blobs: dict[str, str] = {}
    pos = 0
    for path in paths:
        end = out.index(b"\n", pos)
        header = out[pos:end]
        pos = end + 1
        if header.endswith((b" missing", b" ambiguous")):
            continue
        _, kind, size = header.rsplit(b" ", 2)
        data = out[pos : pos + int(size)]
        pos += int(size) + 1
        if kind == b"blob":
            try:
                blobs[path] = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                pass
    return blobs
