import ast
import inspect
import io
import re
import tokenize

from no_comments.langs import Comment, Kind, ParseError

_NEWLINE = re.compile(r"\r\n|\r|\n")


def _docstrings(tree: ast.AST, lines: list[str]) -> list[Comment]:
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        line = lines[node.lineno - 1]
        col = len(line.encode("utf-8")[: node.col_offset].decode("utf-8"))
        found.append(
            Comment(
                node.lineno,
                col + 1,
                line[col:],
                Kind.DOCSTRING,
                inspect.cleandoc(node.value.value),
                node.end_lineno or node.lineno,
            )
        )
    return found


def extract(source: str) -> list[Comment]:
    try:
        comments = [
            Comment(tok.start[0], tok.start[1] + 1, tok.string)
            for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type == tokenize.COMMENT
        ]
        tree = ast.parse(source)
    except (tokenize.TokenError, SyntaxError, ValueError) as exc:
        raise ParseError(str(exc)) from exc
    found = comments + _docstrings(tree, _NEWLINE.split(source))
    return sorted(found, key=lambda c: (c.line, c.col))
