from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

from no_comments.langs import Comment, Kind

Pool = Counter[tuple[Kind, str]]


def pool(versions: Iterable[Sequence[Comment]]) -> Pool:
    return Counter(c.key for comments in versions for c in comments)


def new_comments(
    current: Mapping[str, tuple[Sequence[Comment], set[int]]], previous: Iterable[Pool]
) -> list[tuple[str, Comment]]:
    old: Pool = Counter()
    for version in previous:
        old |= version
    surplus = pool(comments for comments, _ in current.values())
    surplus.subtract(old)
    found = []
    for path in sorted(current):
        comments, added = current[path]
        for comment in comments:
            if surplus[comment.key] > 0 and any(n in added for n in comment.lines):
                found.append((path, comment))
                surplus[comment.key] -= 1
    return found
