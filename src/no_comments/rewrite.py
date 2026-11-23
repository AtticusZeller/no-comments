import ast
import codecs
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

from no_comments.detect import detect_language
from no_comments.langs import Comment, Kind, ParseError, python, shell
from no_comments.report import format_violation
from no_comments.strip import python_code, shell_code

_LOCATION = re.compile(r"(.+):([1-9][0-9]*):([1-9][0-9]*)")
_AUDIT = re.compile(r"(.+?:[1-9][0-9]*:[1-9][0-9]*): NC00[12] \w+ not allowed: ")
_DECISIONS = {"DELETE", "KEEP", "WORKAROUND", "ENCODE"}
_APPLY = {"DELETE", "KEEP"}


@dataclass(frozen=True)
class Review:
    name: str
    line: int
    col: int
    decision: str
    suggestion: str

    @property
    def location(self) -> str:
        return f"{self.name}:{self.line}:{self.col}"


@dataclass(frozen=True, order=True)
class Edit:
    start: int
    end: int
    text: str = ""


def read_review(table: Path) -> dict[Path, list[Review]]:
    files: dict[Path, list[Review]] = defaultdict(list)
    seen: set[tuple[Path, int, int]] = set()
    for number, row in enumerate(table.read_text(encoding="utf-8-sig").split("\n"), 1):
        if not row.strip():
            continue
        parts = row.split(" | ", 4)
        match = _LOCATION.fullmatch(parts[0])
        if len(parts) != 5 or match is None or parts[1] not in _DECISIONS:
            raise ParseError(f"{table}:{number}: invalid review row")
        name, line, col = match.groups()
        try:
            review = Review(name, int(line), int(col), parts[1], parts[4].strip())
        except ValueError as exc:
            raise ParseError(f"{table}:{number}: invalid line or column") from exc
        if review.decision == "KEEP" and not (
            review.suggestion.startswith("# KEEP: ") and review.suggestion[8:].strip()
        ):
            raise ParseError(f"{review.location}: expected a '# KEEP: …' suggestion")
        path = Path(name).resolve()
        key = (path, review.line, review.col)
        if key in seen:
            raise ParseError(f"{review.location}: duplicate review location")
        seen.add(key)
        files[path].append(review)
    return files


def read_audit(audit: Path) -> dict[str, str]:
    entries = {}
    for row in audit.read_text(encoding="utf-8-sig").split("\n"):
        match = _AUDIT.match(row)
        if match is not None:
            location = match[1]
            if location in entries:
                raise ParseError(f"{location}: duplicate audit location")
            entries[location] = row
    return entries


def erase_segments(
    offset: int, body: str, cols: list[int], selected: list[Review | None]
) -> list[Edit]:
    edits = []
    i = 0
    while i < len(cols):
        if selected[i] is None:
            i += 1
            continue
        first = i
        while i < len(cols) and selected[i] is not None:
            i += 1
        start = cols[first]
        left = len(body[:start].rstrip(" \t"))
        if i == len(cols):
            edits.append(Edit(offset + left, offset + len(body)))
        else:
            gap = " " if first and start - left == 1 else ""
            edits.append(Edit(offset + start, offset + cols[i], gap))
    if selected[-1] is None:
        end = len(body.rstrip(" \t"))
        if end < len(body):
            edits.append(Edit(offset + end, offset + len(body)))
    return edits


def comment_edits(
    lines: list[str],
    starts: list[int],
    comments: list[Comment],
    actions: dict[tuple[int, int], Review],
) -> list[Edit]:
    by_line: dict[int, list[Comment]] = defaultdict(list)
    for comment in comments:
        if comment.kind is Kind.COMMENT:
            by_line[comment.line - 1].append(comment)
    standalone = {
        row for row, segments in by_line.items() if not lines[row][: segments[0].col - 1].strip()
    }
    insertions: dict[int, list[str]] = defaultdict(list)
    edits = []
    for row, segments in by_line.items():
        source_line = lines[row]
        body = source_line.rstrip("\r\n")
        selected = [actions.get((c.line, c.col)) for c in segments]
        if not any(selected):
            continue
        if row in standalone and all(selected):
            edits.append(Edit(starts[row], starts[row + 1]))
        else:
            edits.extend(erase_segments(starts[row], body, [c.col - 1 for c in segments], selected))
        keep = [r.suggestion for r in selected if r is not None and r.decision == "KEEP"]
        if keep:
            target = row
            if row in standalone:
                while target < len(lines) and (target in standalone or not lines[target].strip()):
                    target += 1
                if target == len(lines):
                    target = row
            while target and (
                target - 1 not in by_line and lines[target - 1].rstrip("\r\n").endswith("\\")
            ):
                target -= 1
            indent = re.match(r"[ \t\f]*", lines[target])
            assert indent is not None
            newline = lines[target][len(lines[target].rstrip("\r\n")) :] or "\n"
            insertions[starts[target]].extend(indent[0] + text + newline for text in keep)
    return edits + [Edit(pos, pos, "".join(text)) for pos, text in insertions.items()]


def docstring_edits(
    source: str,
    lines: list[str],
    starts: list[int],
    actions: dict[tuple[int, int], Review],
) -> list[Edit]:
    tree = python.parse_tree(source)
    edits = []
    for node in ast.walk(tree):
        for _, suite in ast.iter_fields(node):
            if not isinstance(suite, list):
                continue
            removed = []
            for stmt in suite:
                if not isinstance(stmt, ast.Expr) or python.docstring_value(stmt) is None:
                    continue
                row = stmt.lineno - 1
                col = python.char_col(lines[row], stmt.col_offset)
                review = actions.get((row + 1, col + 1))
                if review is None:
                    continue
                assert stmt.end_lineno is not None and stmt.end_col_offset is not None
                last = stmt.end_lineno - 1
                end_col = python.char_col(lines[last], stmt.end_col_offset)
                start, end = starts[row] + col, starts[last] + end_col
                if review.decision == "KEEP":
                    content = review.suggestion[2:].replace("\\", "\\\\").replace('"', '\\"')
                    edits.append(Edit(start, end, f'"""{content}"""'))
                else:
                    removed.append((row, col, last, end_col, start, end))
            for i, (row, col, last, end_col, start, end) in enumerate(removed):
                suffix = lines[last][end_col:]
                if len(removed) == len(suite) and not isinstance(node, ast.Module) and i == 0:
                    edits.append(Edit(start, end, "..."))
                elif not lines[row][:col].strip() and not suffix.strip():
                    edits.append(Edit(starts[row], starts[last + 1]))
                else:
                    separator = re.match(r"[ \t]*;[ \t]*", suffix)
                    edits.append(Edit(start, end + (separator.end() if separator else 0)))
    return edits


def checked_actions(
    found: dict[tuple[int, int], Comment], reviews: list[Review], audit: dict[str, str]
) -> dict[tuple[int, int], Review]:
    actions = {}
    for review in reviews:
        key = (review.line, review.col)
        comment = found.get(key)
        if comment is None or audit.get(review.location) != format_violation(review.name, comment):
            raise ParseError(f"{review.location}: does not match the saved audit output")
        if review.decision in _APPLY:
            actions[key] = review
    return actions


def rewrite(path: Path, reviews: list[Review], audit: dict[str, str]) -> bytes | None:
    lang = detect_language(path)
    if lang is None:
        raise ParseError(f"{reviews[0].location}: not a supported source file")
    data = path.read_bytes()
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(f"{path}: not UTF-8") from exc
    extract = python.extract if lang == "python" else shell.extract
    comments = extract(source)
    found = {(c.line, c.col): c for c in comments}
    actions = checked_actions(found, reviews, audit)
    if not actions:
        return None
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+", source)
    starts = list(accumulate(map(len, lines), initial=0))
    edits = comment_edits(lines, starts, comments, actions)
    if any(found[key].kind is Kind.DOCSTRING for key in actions):
        edits.extend(docstring_edits(source, lines, starts, actions))
    boundary = len(source)
    parts = []
    for edit in sorted(edits, reverse=True):
        if edit.end > boundary:
            raise ParseError(f"{path}: overlapping comment and docstring edits")
        parts.extend((source[edit.end : boundary], edit.text))
        boundary = edit.start
    parts.append(source[:boundary])
    rewritten = "".join(reversed(parts))
    code = python_code if lang == "python" else shell_code
    if code(rewritten) != code(source):
        raise ParseError(f"{path}: rewriting would change code")
    expected = Counter(c.key for c in comments if (c.line, c.col) not in actions)
    expected.update(
        (found[key].kind, row.suggestion[2:])
        for key, row in actions.items()
        if row.decision == "KEEP"
    )
    if Counter(c.key for c in extract(rewritten)) != expected:
        raise ParseError(f"{path}: rewritten comments do not match the review")
    bom = codecs.BOM_UTF8 if data.startswith(codecs.BOM_UTF8) else b""
    return bom + rewritten.encode("utf-8")


def run_strip(table: Path, snapshot: Path) -> int:
    audit = read_audit(snapshot)
    outputs = []
    for path, reviews in read_review(table).items():
        output = rewrite(path, reviews, audit)
        if output is not None:
            outputs.append((path, output))
    for path, output in outputs:
        path.write_bytes(output)
    return 0
