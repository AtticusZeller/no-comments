import tree_sitter_bash
from tree_sitter import Language, Node, Parser

from no_comments.langs import Comment, comment_segments

_PARSER = Parser(Language(tree_sitter_bash.language()))


def _comment_nodes(root: Node) -> list[Node]:
    found: list[Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment":
            found.append(node)
        stack.extend(node.children)
    return sorted(found, key=lambda n: n.start_byte)


def ends_with_escape(text: str) -> bool:
    return (len(text) - len(text.rstrip("\\"))) % 2 == 1


def separator_start(prefix: str) -> int:
    end = len(prefix.rstrip(" \t"))
    if end < len(prefix) and ends_with_escape(prefix[:end]):
        return end + 1
    return end


def statement_starts(source: str) -> dict[int, int]:
    root = _PARSER.parse(source.encode("utf-8")).root_node
    starts = {}
    for comment in _comment_nodes(root):
        row = comment.start_point.row
        parent = comment.parent
        outer = parent.parent if parent is not None else None
        if (
            parent is not None
            and parent.type.endswith("_redirect")
            and outer is not None
            and outer.type == "redirected_statement"
        ):
            starts[row] = outer.start_point.row
            continue
        prior = comment.prev_named_sibling
        if prior is not None and prior.type != "comment" and prior.end_point.row == row:
            starts[row] = prior.start_point.row
        elif parent is not None and parent != root:
            starts[row] = parent.start_point.row
    return starts


def code_lines(source: str) -> list[str]:
    data = source.encode("utf-8")
    lines = data.split(b"\n")
    comment_cols = {
        node.start_point.row: node.start_point.column
        for node in _comment_nodes(_PARSER.parse(data).root_node)
    }
    code = []
    continued = False
    for row, raw in enumerate(lines):
        raw_line = raw[: comment_cols.get(row)].decode("utf-8")
        line = raw_line.removesuffix("\r")
        if line.strip() or continued:
            code.append(line[: separator_start(line)])
        continued = row not in comment_cols and ends_with_escape(raw_line)
    return code


def extract(source: str) -> list[Comment]:
    data = source.encode("utf-8")
    lines = data.split(b"\n")
    comments = []
    for node in _comment_nodes(_PARSER.parse(data).root_node):
        row, byte_col = node.start_point
        col = len(lines[row][:byte_col].decode("utf-8")) + 1
        text = data[node.start_byte : node.end_byte].decode("utf-8")
        comments += comment_segments(row + 1, col, text)
    return comments
