from collections.abc import Iterable

from no_comments.langs import Comment

HINT = (
    "删除这些注释。要表达的内容放进命名、类型或测试里；改动说明写进 commit message。"
    "只有代码无法表达的外部约束，才改写成 `# KEEP: <原因>`。"
)


def format_violation(path: str, comment: Comment) -> str:
    return f"{path}:{comment.line}:{comment.col}: NC001 comment not allowed: {comment.text[:60]}"


def print_violations(violations: Iterable[tuple[str, Comment]]) -> None:
    for path, comment in violations:
        print(format_violation(path, comment))


def print_hint() -> None:
    print()
    print(HINT)
