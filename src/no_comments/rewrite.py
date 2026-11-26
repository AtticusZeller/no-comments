import ast
import codecs
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path

from no_comments.allow import is_allowed
from no_comments.detect import detect_language, through_symlink
from no_comments.langs import (
    Comment,
    Kind,
    ParseError,
    comment_segments,
    python,
    shell,
    typescript,
)
from no_comments.report import format_violation
from no_comments.strip import changed_header, python_code

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
        path = Path(name).absolute()
        if through_symlink(path):
            raise ParseError(f"{review.location}: symbolic links are not supported")
        path = Path(os.path.normpath(path))
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
    offset: int,
    body: str,
    cols: list[int],
    selected: list[Review | None],
    lang: str,
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
        blanks = " \t" if lang == "shell" else None
        left = len(body[:start].rstrip(blanks))
        if i == len(cols):
            if first == 0 and lang == "shell":
                left = shell.separator_start(body[:start])
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
    source: str,
    lines: list[str],
    starts: list[int],
    comments: list[Comment],
    actions: dict[tuple[int, int], Review],
    doc_edits: list[Edit],
    lang: str,
) -> list[Edit]:
    by_line: dict[int, list[Comment]] = defaultdict(list)
    insertions: dict[int, list[str]] = defaultdict(list)
    statement_starts = (
        python.statement_starts(source) if lang == "python" else shell.statement_starts(source)
    )
    for comment in comments:
        if comment.kind is not Kind.COMMENT:
            continue
        row = comment.line - 1
        position = starts[row] + comment.col - 1
        if not any(edit.start <= position < edit.end for edit in doc_edits):
            by_line[row].append(comment)
            continue
        review = actions.get((comment.line, comment.col))
        if review is None or review.decision == "KEEP":
            target = statement_starts.get(row, row)
            insertions[target].append(comment.text if review is None else review.suggestion)
    blanks = " \t" if lang == "shell" else None
    standalone = {
        row
        for row, segments in by_line.items()
        if not lines[row][: segments[0].col - 1].strip(blanks)
    }
    edits = []
    for row, segments in by_line.items():
        source_line = lines[row]
        body = source_line.rstrip("\r\n")
        selected = [actions.get((c.line, c.col)) for c in segments]
        if not any(selected):
            continue
        if row in standalone and all(selected):
            continued = (
                lang == "shell"
                and row > 0
                and row - 1 not in by_line
                and shell.ends_with_escape(lines[row - 1].rstrip("\n"))
            )
            end = starts[row] + len(body) if continued else starts[row + 1]
            edits.append(Edit(starts[row], end))
        else:
            edits.extend(
                erase_segments(starts[row], body, [c.col - 1 for c in segments], selected, lang)
            )
        keep = [r.suggestion for r in selected if r is not None and r.decision == "KEEP"]
        if keep:
            target = row
            if row in standalone:
                while target < len(lines) and (
                    target in standalone or not lines[target].rstrip("\r\n").strip(blanks)
                ):
                    target += 1
                if target == len(lines):
                    target = row
            target = statement_starts.get(target, target)
            insertions[target].extend(keep)
    for row, texts in insertions.items():
        indent = re.match(r"[ \t]*" if lang == "shell" else r"[ \t\f]*", lines[row])
        assert indent is not None
        newline = lines[row][len(lines[row].rstrip("\r\n")) :] or "\n"
        pos = starts[row]
        edits.append(Edit(pos, pos, "".join(indent[0] + text + newline for text in texts)))
    return edits


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
    found: dict[tuple[int, int], Comment],
    reviews: list[Review],
    audit: dict[str, str],
    lang: str,
    protected: dict[tuple[int, int], str] | None = None,
) -> dict[tuple[int, int], Review]:
    actions = {}
    for review in reviews:
        key = (review.line, review.col)
        if review.decision in _APPLY and protected is not None and key in protected:
            raise ParseError(
                f"{review.location}: compiler directive {protected[key]} must be handled as "
                "WORKAROUND or ENCODE; change the code or configuration before removing it manually"
            )
        comment = found.get(key)
        if comment is None or audit.get(review.location) != format_violation(review.name, comment):
            raise ParseError(f"{review.location}: does not match the saved audit output")
        if lang in typescript.TS_LANGUAGES:
            if is_allowed(lang, comment):
                raise ParseError(f"{review.location}: comment is allowed by default")
            if review.decision == "KEEP":
                ts_keep_body(review)
        elif review.decision == "KEEP":
            if not (review.suggestion.startswith("# KEEP: ") and review.suggestion[8:].strip()):
                raise ParseError(f"{review.location}: expected a '# KEEP: …' suggestion")
            if len(comment_segments(1, 1, review.suggestion)) != 1:
                raise ParseError(
                    f"{review.location}: KEEP suggestion must be a single comment segment"
                )
        if review.decision in _APPLY:
            actions[key] = review
    return actions


def ts_keep_body(review: Review) -> str:
    text = review.suggestion
    if text.startswith("// "):
        body = text[3:]
    elif text.startswith("/* ") and text.endswith(" */"):
        body = text[3:-3]
    else:
        body = ""
    if (
        not body.startswith("KEEP: ")
        or not body[6:].strip()
        or re.search(r"[\r\n\u2028\u2029]|\*/", body)
    ):
        raise ParseError(f"{review.location}: expected a single TypeScript KEEP comment")
    return body


_TS_BLANK = re.compile(r"[\s\ufeff]*")
_TS_NEWLINE = re.compile(rb"\r\n|[\r\n]|\xe2\x80[\xa8\xa9]")


def _ts_edit(data: bytes, span: typescript.CommentSpan, action: Review) -> tuple[int, int, bytes]:
    start, end = span.start, span.end
    original = data[start:end]
    newline = _TS_NEWLINE.search(original)
    line_comment = original.startswith(b"//")
    line_end = _TS_NEWLINE.search(data, end)
    suffix_end = line_end.start() if line_end is not None else len(data)
    if action.decision == "KEEP":
        body = ts_keep_body(action).encode()
        if line_comment:
            return start, end, b"// " + body
        separator = newline[0] if newline and data[end:suffix_end].strip(b" \t") else b" "
        return start, end, b"/* " + body + separator + b"*/"
    if span.wrapper is not None:
        return start, end, b""
    if not data[end:suffix_end].strip(b" \t"):
        while start and data[start - 1 : start] in (b" ", b"\t"):
            start -= 1
        return start, suffix_end, newline[0] if newline else b""
    if newline:
        return start, end, newline[0]
    if (
        start
        and end < len(data)
        and data[start - 1 : start] not in b" \t\r\n"
        and data[end : end + 1] not in b" \t\r\n"
    ):
        return start, end, b" "
    return start, end, b""


def _apply_ts_edits(data: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    parts = []
    pos = row = 0
    affected: set[int] = set()
    for start, end, replacement in sorted(edits):
        intact = data[pos:start]
        row += len(_TS_NEWLINE.findall(intact))
        end_row = row + len(_TS_NEWLINE.findall(replacement))
        affected.update(range(row, end_row + 1))
        parts.extend((intact, replacement))
        row = end_row
        pos = end
    parts.append(data[pos:])
    output = b"".join(parts)
    lines = _TS_NEWLINE.split(output)
    endings = [*_TS_NEWLINE.findall(output), b""]
    return b"".join(
        line + ending
        for i, (line, ending) in enumerate(zip(lines, endings, strict=True))
        if i not in affected or not _TS_BLANK.fullmatch(line.decode())
    )


def rewrite_typescript(
    path: Path, reviews: list[Review], audit: dict[str, str], data: bytes, source: str, lang: str
) -> bytes | None:
    original = source.encode()
    try:
        spans = typescript.comment_spans(original, lang)
        located = {(span.comment.line, span.comment.col): span for span in spans}
        directives = typescript.compiler_directives(source, lang)
        protected = {
            key: directive.name
            for key, span in located.items()
            for directive in directives
            if span.start < directive.end and directive.start < span.end
        }
        actions = checked_actions(
            {key: span.comment for key, span in located.items()}, reviews, audit, lang, protected
        )
        if not actions:
            return None
        wrappers: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for key, span in located.items():
            if span.wrapper is not None:
                wrappers[span.wrapper].append(key)
        remove_wrappers = {
            wrapper
            for wrapper, keys in wrappers.items()
            if all(key in actions and actions[key].decision == "DELETE" for key in keys)
        }
        edits = [(start, end, b"") for start, end in remove_wrappers]
        for key, action in actions.items():
            span = located[key]
            if span.wrapper not in remove_wrappers:
                edits.append(_ts_edit(original, span, action))
        rewritten = _apply_ts_edits(original, edits)
        output = (codecs.BOM_UTF8 if data.startswith(codecs.BOM_UTF8) else b"") + rewritten
        if reason := changed_header(data, output, lang):
            raise ParseError(reason)
        rewritten_source = rewritten.decode()
        changed = typescript.changed_directives(
            directives, typescript.compiler_directives(rewritten_source, lang)
        )
        if changed:
            raise ParseError(
                f"rewriting would change compiler directive {', '.join(changed)}; use WORKAROUND or ENCODE"
            )
        if typescript.code_signature(source, lang) != typescript.code_signature(
            rewritten_source, lang
        ):
            raise ParseError("rewriting would change code")
        expected = Counter(span.comment.key for key, span in located.items() if key not in actions)
        expected.update(
            (Kind.COMMENT, ts_keep_body(action))
            for action in actions.values()
            if action.decision == "KEEP"
        )
        if (
            Counter(span.comment.key for span in typescript.comment_spans(rewritten, lang))
            != expected
        ):
            raise ParseError("rewritten comments do not match the review")
        return output
    except ParseError as exc:
        raise ParseError(f"{path}: {exc}") from exc


def rewrite(path: Path, reviews: list[Review], audit: dict[str, str]) -> bytes | None:
    lang = detect_language(path)
    if lang is None:
        raise ParseError(f"{reviews[0].location}: not a supported source file")
    data = path.read_bytes()
    try:
        if lang == "python":
            python.require_utf8(data)
        source = data.decode("utf-8-sig")
    except ParseError as exc:
        raise ParseError(f"{path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise ParseError(f"{path}: not UTF-8") from exc
    if lang in typescript.TS_LANGUAGES:
        return rewrite_typescript(path, reviews, audit, data, source, lang)
    extract = python.extract if lang == "python" else shell.extract
    comments = extract(source)
    found = {(c.line, c.col): c for c in comments}
    actions = checked_actions(found, reviews, audit, lang)
    if not actions:
        return None
    lines = re.findall(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+", source)
    starts = list(accumulate(map(len, lines), initial=0))
    doc_edits = docstring_edits(source, lines, starts, actions) if lang == "python" else []
    edits = doc_edits + comment_edits(source, lines, starts, comments, actions, doc_edits, lang)
    boundary = len(source)
    parts = []
    for edit in sorted(edits, reverse=True):
        if edit.end > boundary:
            raise ParseError(f"{path}: overlapping comment and docstring edits")
        parts.extend((source[edit.end : boundary], edit.text))
        boundary = edit.start
    parts.append(source[:boundary])
    rewritten = "".join(reversed(parts))
    bom = codecs.BOM_UTF8 if data.startswith(codecs.BOM_UTF8) else b""
    output = bom + rewritten.encode("utf-8")
    if reason := changed_header(data, output, lang):
        raise ParseError(f"{path}: {reason}")
    code = python_code if lang == "python" else shell.code_lines
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
    return output


def run_strip(table: Path, snapshot: Path) -> int:
    audit = read_audit(snapshot)
    outputs = []
    for path, reviews in read_review(table).items():
        output = rewrite(path, reviews, audit)
        if output is not None:
            outputs.append((path, output))
    written = []
    for path, output in outputs:
        try:
            if through_symlink(path):
                raise OSError("symbolic links are not supported")
            path.write_bytes(output)
        except OSError as exc:
            completed = ", ".join(written) or "none"
            raise ParseError(
                f"could not write {path}: {exc}; already written: {completed}"
            ) from exc
        written.append(str(path))
    return 0
