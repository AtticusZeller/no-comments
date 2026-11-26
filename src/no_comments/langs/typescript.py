import re

import tree_sitter_typescript
from tree_sitter import Language, Parser, Query, QueryCursor

from no_comments.langs import Comment, ParseError

_TS = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())
_PARSERS = {language: Parser(language) for language in (_TS, _TSX)}
_QUERIES = {language: Query(language, "(comment) @comment") for language in (_TS, _TSX)}
_SEGMENT = re.compile(r"[ \t]+(?=//)")
BIOME_PREFIX = "biome-ignore"
REFERENCE_PREFIX = "<reference"
_BIOME = re.compile(
    rf"{BIOME_PREFIX}"
    r"[ \t]+(?:format|(?:lint|assist|syntax)(?:/[\w-]+){0,2})"
    r"(?:\([^\r\n()]+\))?[ \t]*:[ \t]*\S"
)
_ATTRIBUTE = re.compile(r"""([a-z-]+)[ \t]*=[ \t]*(?:"([^"\r\n]*)"|'([^'\r\n]*)')""")
_REFERENCE = re.compile(rf"{REFERENCE_PREFIX}(?:[ \t]+{_ATTRIBUTE.pattern})+[ \t]*/>")
_BLOCK_MARGIN = re.compile(r"^[ \t]*\* ?", re.MULTILINE)


def _reference(text: str) -> bool:
    if not _REFERENCE.fullmatch(text):
        return False
    pairs = _ATTRIBUTE.findall(text)
    attrs = {name: double or single for name, double, single in pairs}
    if len(attrs) != len(pairs):
        return False
    if "preserve" in attrs and attrs.pop("preserve") not in {"true", "false"}:
        return False
    if "resolution-mode" in attrs and (
        "types" not in attrs or attrs.pop("resolution-mode") not in {"import", "require"}
    ):
        return False
    return len(attrs) == 1 and (
        any(attrs.get(name) for name in ("path", "types", "lib"))
        or attrs.get("no-default-lib") == "true"
    )


def is_directive(comment: Comment) -> bool:
    if comment.text.startswith("///"):
        return (
            comment.file_header and not comment.text.startswith("////") and _reference(comment.body)
        )
    return _BIOME.match(comment.body) is not None


def _line_comments(row: int, col: int, text: str, file_header: bool) -> list[Comment]:
    text = text.rstrip()
    markers = len(text) - len(text.lstrip("/"))
    body_start = len(text) - len(text[markers:].lstrip())
    body = text[body_start:]
    start = body_start
    if markers == 3 and (tag := _REFERENCE.match(body)):
        start += tag.end()
    starts = [0]
    if body.startswith(BIOME_PREFIX) or (markers == 3 and start > body_start):
        starts.extend(match.end() for match in _SEGMENT.finditer(text, start))
    ends = starts[1:] + [len(text)]
    return [
        Comment(
            row,
            col + offset,
            text[offset:end].rstrip(),
            content=text[offset:end].lstrip("/").strip(),
            file_header=file_header and offset == 0,
        )
        for offset, end in zip(starts, ends, strict=True)
    ]


def _extract(source: str, language: Language) -> list[Comment]:
    data = source.encode("utf-8")
    root = _PARSERS[language].parse(data).root_node
    if root.has_error:
        raise ParseError("invalid TypeScript or TSX syntax")
    lines = data.split(b"\n")
    header_end = next(
        (
            node.start_byte
            for node in root.named_children
            if node.type not in {"comment", "hash_bang_line"}
        ),
        len(data),
    )
    captures = QueryCursor(_QUERIES[language]).captures(root)
    comments = []
    for node in sorted(captures.get("comment", []), key=lambda n: n.start_byte):
        row, byte_col = node.start_point
        col = len(lines[row][:byte_col].decode("utf-8")) + 1
        text = data[node.start_byte : node.end_byte].decode("utf-8")
        if text.startswith("//"):
            comments.extend(_line_comments(row + 1, col, text, node.start_byte < header_end))
        else:
            body = _BLOCK_MARGIN.sub("", text[2:-2])
            content = "\n".join(line.strip() for line in body.splitlines()).strip()
            comments.append(
                Comment(row + 1, col, text, content=content, end_line=node.end_point.row + 1)
            )
    return comments


def extract(source: str) -> list[Comment]:
    return _extract(source, _TS)


def extract_tsx(source: str) -> list[Comment]:
    return _extract(source, _TSX)
