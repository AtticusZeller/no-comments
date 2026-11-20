import tree_sitter_bash
from tree_sitter import Language, Node, Parser

from no_comments.langs import Comment

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


def extract(source: str) -> list[Comment]:
    data = source.encode("utf-8")
    lines = data.split(b"\n")
    comments = []
    for node in _comment_nodes(_PARSER.parse(data).root_node):
        row, byte_col = node.start_point
        col = len(lines[row][:byte_col].decode("utf-8")) + 1
        comments.append(Comment(row + 1, col, node.text.decode("utf-8")))
    return comments
