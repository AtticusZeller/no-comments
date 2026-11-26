import re
from collections.abc import Iterator
from dataclasses import dataclass

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from no_comments.langs import Comment, ParseError

_TS = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())
_PARSERS = {language: Parser(language) for language in (_TS, _TSX)}
_QUERIES = {language: Query(language, "(comment) @comment") for language in (_TS, _TSX)}
_SEGMENT = re.compile(r"[ \t]+(?=//)(?!//(?:[a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+(?=[/:?#\s]|$))")
BIOME_PREFIX = "biome-ignore"
REFERENCE_PREFIX = "<reference"
_BIOME_SELECTOR = r"(?:format|(?:lint|assist|syntax)(?:/[\w-]+){0,2})(?:\([^\r\n()]+\))?"
_BIOME = re.compile(rf"{BIOME_PREFIX}(?:[ \t]+{_BIOME_SELECTOR})+[ \t]*:[ \t]*\S")
_ATTRIBUTE = re.compile(r"""([a-z-]+)[ \t]*=[ \t]*(?:"([^"\r\n]*)"|'([^'\r\n]*)')""")
_REFERENCE = re.compile(rf"{REFERENCE_PREFIX}(?:[ \t]+{_ATTRIBUTE.pattern})+[ \t]*/>")
_BLOCK_MARGIN = re.compile(r"^[ \t]*\* ?", re.MULTILINE)


_LINE_BREAK = re.compile(rb"[\r\n]|\xe2\x80[\xa8\xa9]")
_NO_LINE_BREAK_AFTER = {"return", "throw", "break", "continue", "yield", "async"}
_NO_LINE_BREAK_BEFORE = {"++", "--", "=>"}
TS_LANGUAGES = {"typescript", "tsx"}
Syntax = tuple[tuple[str, bytes], ...]


@dataclass(frozen=True)
class CommentSpan:
    comment: Comment
    start: int
    end: int
    wrapper: tuple[int, int] | None = None


class TypeScriptParseError(ParseError):
    pass


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


def _unsupported_modifier(node: Node, data: bytes) -> Node | None:
    error = next((child for child in node.named_children if child.is_error), None)
    if error is None:
        return None
    text = data[error.start_byte : error.end_byte]
    on_right = (child for child in node.children if child.start_byte >= error.end_byte)
    following = next((child for child in on_right if child.type != "comment"), None)
    if following is not None:
        if (
            node.type == "export_statement"
            and text == b"type"
            and following.type in {"*", "namespace_export"}
        ):
            return error
        if (
            node.type == "import_statement"
            and text == b"defer"
            and following.type == "import_clause"
            and any(c.type == "namespace_import" for c in following.named_children)
        ):
            return error
    return None


def _error_nodes(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for child in reversed(node.children) if child.has_error)


def _tokens(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            continue
        if node.type in {"string", "template_string", "regex", "jsx_text"} or not node.child_count:
            if not node.is_missing:
                yield node
        else:
            stack.extend(reversed(node.children))


def _attribute_end(tokens: list[Node], opening: int) -> int | None:
    depth = 0
    for i in range(opening, len(tokens)):
        token = tokens[i]
        if token.type == "{":
            depth += 1
        elif token.type == "}":
            depth -= 1
            if depth == 0:
                return token.end_byte
    return None


def _mask_attributes(parser: Parser, query: Query, clause: bytes) -> tuple[bytes, Syntax] | None:
    prefix = b'import "module" '
    root = parser.parse(prefix + clause + b";").root_node
    if root.has_error or len(root.named_children) != 1:
        return None
    statement = root.named_children[0]
    attribute = next((c for c in statement.named_children if c.type == "import_attribute"), None)
    if attribute is None:
        return None
    attributes = next((c for c in attribute.named_children if c.type == "object"), None)
    if attributes is None:
        return None
    for item in attributes.named_children:
        if item.type == "comment":
            continue
        key, value = item.child_by_field_name("key"), item.child_by_field_name("value")
        if (
            item.type != "pair"
            or key is None
            or key.type not in {"property_identifier", "string"}
            or value is None
            or value.type != "string"
        ):
            return None
    masked = bytearray(re.sub(rb"[^\r\n]", b" ", clause))
    for comment in QueryCursor(query).captures(root).get("comment", []):
        start, end = comment.start_byte - len(prefix), comment.end_byte - len(prefix)
        masked[start:end] = clause[start:end]
    tokens = tuple(
        (token.type, clause[token.start_byte - len(prefix) : token.end_byte - len(prefix)])
        for token in _tokens(attribute)
    )
    return bytes(masked), tokens


def _recover_attributes(
    root: Node, parser: Parser, query: Query, data: bytes, adjusted: bytearray
) -> dict[tuple[int, int], Syntax]:
    tokens = list(_tokens(root))
    sources = {}
    for i, (source, keyword, opening) in enumerate(
        zip(tokens, tokens[1:], tokens[2:], strict=False)
    ):
        if source.type != "string" or keyword.type != "with" or opening.type != "{":
            continue
        if keyword.parent is not None and keyword.parent.type == "import_attribute":
            continue
        end = _attribute_end(tokens, i + 2)
        if end is None:
            continue
        start = keyword.start_byte
        if (result := _mask_attributes(parser, query, data[start:end])) is not None:
            masked, syntax = result
            adjusted[start:end] = masked
            sources[(source.start_byte, source.end_byte)] = syntax
    return sources


def _is_module_source(root: Node, start: int, end: int) -> bool:
    node = root.descendant_for_byte_range(start, end)
    if node is None or (parent := node.parent) is None:
        return False
    return parent.type in {"import_statement", "export_statement"} and (
        parent.child_by_field_name("source") == node
    )


def _parse(data: bytes, language: Language, extras: dict[int, Syntax]) -> Node:
    parser = _PARSERS[language]
    root = parser.parse(data).root_node
    if not root.has_error:
        return root
    adjusted = bytearray(data)
    sources = _recover_attributes(root, parser, _QUERIES[language], data, adjusted)
    if sources:
        root = parser.parse(bytes(adjusted)).root_node
    if root.has_error:
        changed = False
        for node in _error_nodes(root):
            if (token := _unsupported_modifier(node, data)) is not None:
                adjusted[token.start_byte : token.end_byte] = b" " * (
                    token.end_byte - token.start_byte
                )
                extras[node.start_byte] = (
                    ("module_modifier", data[token.start_byte : token.end_byte]),
                )
                changed = True
        if changed:
            root = parser.parse(bytes(adjusted)).root_node
    if root.has_error or not all(_is_module_source(root, *source) for source in sources):
        raise TypeScriptParseError("could not parse TypeScript or TSX with Tree-sitter")
    extras.update({end: syntax for (_, end), syntax in sources.items()})
    return root


def _empty_jsx(node: Node) -> bool:
    return (
        node.type == "jsx_expression"
        and node.parent is not None
        and node.parent.type == "jsx_element"
        and all(child.type == "comment" for child in node.named_children)
    )


def comment_spans(data: bytes, lang: str) -> list[CommentSpan]:
    language = _TSX if lang == "tsx" else _TS
    root = _parse(data, language, {})
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
        parent = node.parent
        wrapper = (
            (parent.start_byte, parent.end_byte)
            if parent is not None and _empty_jsx(parent)
            else None
        )
        if text.startswith("//"):
            for item in _line_comments(row + 1, col, text, node.start_byte < header_end):
                start = node.start_byte + len(text[: item.col - col].encode())
                comments.append(CommentSpan(item, start, start + len(item.text.encode()), wrapper))
        else:
            body = _BLOCK_MARGIN.sub("", text[2:-2])
            content = "\n".join(line.strip() for line in body.splitlines()).strip()
            item = Comment(row + 1, col, text, content=content, end_line=node.end_point.row + 1)
            comments.append(CommentSpan(item, node.start_byte, node.end_byte, wrapper))
    return comments


def extract(source: str) -> list[Comment]:
    return [span.comment for span in comment_spans(source.encode(), "typescript")]


def extract_tsx(source: str) -> list[Comment]:
    return [span.comment for span in comment_spans(source.encode(), "tsx")]


def _jsx_text(text: bytes) -> bytes:
    lines = re.split(rb"\r\n|[\r\n]", text)
    if len(lines) == 1:
        return lines[0]
    cleaned = [
        lines[0].rstrip(b" \t"),
        *(line.strip(b" \t") for line in lines[1:-1]),
        lines[-1].lstrip(b" \t"),
    ]
    return b" ".join(line for line in cleaned if line)


def code_signature(source: str, lang: str) -> Syntax:
    data = source.encode()
    extras: dict[int, Syntax] = {}
    root = _parse(data, _TSX if lang == "tsx" else _TS, extras)
    result: list[tuple[str, bytes]] = []
    previous: Node | None = None
    stack: list[tuple[Node, bool]] = [(root, False)]
    while stack:
        node, end = stack.pop()
        if node.type == "comment" or _empty_jsx(node):
            continue
        if node.type == "jsx_text":
            if text := _jsx_text(data[node.start_byte : node.end_byte]):
                result.append(("jsx_text", text))
            previous = None
            continue
        if end:
            result.append(("end", b""))
        elif node.type == "import_attribute":
            result.extend((t.type, data[t.start_byte : t.end_byte]) for t in _tokens(node))
        elif node.type != "program" and (not node.child_count or node.type in {"string", "regex"}):
            if (
                previous is not None
                and (previous.type in _NO_LINE_BREAK_AFTER or node.type in _NO_LINE_BREAK_BEFORE)
                and _LINE_BREAK.search(data, previous.end_byte, node.start_byte)
            ):
                result.append(("restricted_line_break", b""))
            previous = node
            result.append((node.type, data[node.start_byte : node.end_byte]))
            if node.type == "string":
                result.extend(extras.get(node.end_byte, ()))
        else:
            result.append((node.type, b""))
            if node.type in {"import_statement", "export_statement"}:
                result.extend(extras.get(node.start_byte, ()))
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
    return tuple(result)
