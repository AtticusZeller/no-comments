import ast
import inspect
import io
import re
import tokenize
import warnings

from no_comments.langs import Comment, Kind, ParseError, comment_segments

_NEWLINE = re.compile(r"\r\n|\r|\n")
_COOKIE = re.compile(rb"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")
_NON_CODE = {tokenize.INDENT, tokenize.DEDENT, tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER}


def effective_encoding(data: bytes) -> tuple[str, bool]:
    try:
        encoding, prefix = tokenize.detect_encoding(io.BytesIO(data).readline)
    except SyntaxError as exc:
        raise ParseError(f"invalid Python encoding: {exc}") from exc
    return encoding, any(_COOKIE.match(line) for line in prefix)


def statement_starts(source: str) -> dict[int, int]:
    starts = {}
    start = None
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.NEWLINE:
            start = None
        elif tok.type not in _NON_CODE and start is None:
            start = tok.start[0] - 1
        if start is not None:
            for row in range(tok.start[0] - 1, tok.end[0]):
                starts[row] = start
    return starts


def docstring_value(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ):
        return node.value.value
    return None


def parse_tree(source: str) -> ast.Module:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise ParseError(str(exc)) from exc


def char_col(line: str, byte_offset: int) -> int:
    return len(line.encode("utf-8")[:byte_offset].decode("utf-8"))


def _docstrings(tree: ast.AST, lines: list[str]) -> list[Comment]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or (value := docstring_value(node)) is None:
            continue
        line = lines[node.lineno - 1]
        col = char_col(line, node.col_offset)
        found.append(
            Comment(
                node.lineno,
                col + 1,
                line[col:],
                Kind.DOCSTRING,
                inspect.cleandoc(value),
                node.end_lineno or node.lineno,
            )
        )
    return found


def extract(source: str) -> list[Comment]:
    try:
        comments = [
            segment
            for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type == tokenize.COMMENT
            for segment in comment_segments(tok.start[0], tok.start[1] + 1, tok.string)
        ]
    except (tokenize.TokenError, SyntaxError, ValueError) as exc:
        raise ParseError(str(exc)) from exc
    found = comments + _docstrings(parse_tree(source), _NEWLINE.split(source))
    return sorted(found, key=lambda c: (c.line, c.col))
