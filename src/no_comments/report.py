from collections.abc import Iterable

from no_comments.langs import Comment, Kind

CODES = {Kind.COMMENT: "NC001", Kind.DOCSTRING: "NC002"}

HINT = (
    "删除这些注释和 docstring。要表达的内容放进命名、类型或测试里；改动说明写进 commit message。"
    '只有代码无法表达的外部约束，才改写成 `# KEEP: <原因>`（docstring 写成 `"""KEEP: <原因>"""`）。'
    "接口说明交给签名和类型；框架需要的帮助文本或接口描述（typer、FastAPI 等），"
    "用 help=、description= 显式传入。"
)


def format_violation(path: str, comment: Comment) -> str:
    return (
        f"{path}:{comment.line}:{comment.col}: {CODES[comment.kind]} {comment.kind.value} not allowed: "
        f"{comment.text[:60]}"
    )


def print_violations(violations: Iterable[tuple[str, Comment]]) -> None:
    for path, comment in violations:
        print(format_violation(path, comment))


def print_hint() -> None:
    print()
    print(HINT)
