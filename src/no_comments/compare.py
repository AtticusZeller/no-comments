from collections import Counter
from collections.abc import Iterable, Sequence

from no_comments.langs import Comment, Kind


def new_comments(
    current: Sequence[Comment], previous: Iterable[Sequence[Comment]], added: set[int]
) -> list[Comment]:
    old: Counter[tuple[Kind, str]] = Counter()
    for version in previous:
        old |= Counter(c.key for c in version)
    surplus = Counter(c.key for c in current)
    surplus.subtract(old)
    found = []
    for comment in current:
        if surplus[comment.key] > 0 and any(n in added for n in comment.lines):
            found.append(comment)
            surplus[comment.key] -= 1
    return found
