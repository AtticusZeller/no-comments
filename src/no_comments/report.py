import re
from collections.abc import Sequence

from no_comments.langs import Comment, Kind

CODES = {Kind.COMMENT: "NC001", Kind.DOCSTRING: "NC002"}

HINT = (
    "删除这些注释和 docstring。要表达的内容放进命名、类型或测试里；改动说明写进 commit message。"
    '只有代码无法表达的外部约束，才改写成 `# KEEP: <原因>`'
    '（TypeScript 用 `// KEEP: <原因>`，docstring 用 `"""KEEP: <原因>"""`）。'
    "接口说明交给签名和类型；框架需要的帮助文本或接口描述（typer、FastAPI 等），"
    "用 help=、description= 显式传入。"
)

SHAPE_HINT = (
    '检测到张量形状注释：把形状写进 jaxtyping 类型标注（如 `Float[Tensor, "V 3 10"]`），'
    "并在测试中用 `--jaxtyping-packages` 开启运行时检查。"
)

_TERM = r"(?:\d*[A-Za-z_]\w*'*|\d+|\.\.\.|\*(?:[A-Za-z_]\w*)?)"
_DIM = rf"{_TERM}(?:\s*(?:\*\*|//|[*+\-/])\s*{_TERM})*"
_SHAPE = re.compile(rf"[(\[]\s*{_DIM}(?:\s*,\s*{_DIM})*(?:\s*,\s*{_DIM}|\s*,)\s*[)\]]")


def is_shape(comment: Comment) -> bool:
    return comment.kind is Kind.COMMENT and _SHAPE.match(comment.body) is not None


def format_violation(path: str, comment: Comment) -> str:
    rule = f"{CODES[comment.kind]} {comment.kind.value} not allowed"
    preview = comment.text.replace("\r\n", "\n").replace("\n", r"\n")[:60]
    return f"{path}:{comment.line}:{comment.col}: {rule}: {preview}"


def print_violations(violations: Sequence[tuple[str, Comment]]) -> None:
    for path, comment in violations:
        print(format_violation(path, comment))


def print_hint(violations: Sequence[tuple[str, Comment]]) -> None:
    print()
    print(HINT)
    if any(is_shape(comment) for _, comment in violations):
        print(SHAPE_HINT)
