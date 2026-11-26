from collections import Counter
from collections.abc import Iterable, Mapping, Sequence, Set

from no_comments.langs import Comment, Kind

Pool = Counter[tuple[Kind, str]]


def pool(versions: Iterable[Sequence[Comment]]) -> Pool:
    return Counter(c.key for comments in versions for c in comments)


def retained_comments(
    old: Sequence[Comment], new: Sequence[Comment], replaced: Mapping[int, int]
) -> Iterable[Comment]:
    positions = Counter((c.line, c.key) for c in old)
    for comment in new:
        for line in comment.lines:
            if (old_line := replaced.get(line)) is None:
                continue
            position = (old_line - (line - comment.line), comment.key)
            if positions[position] > 0:
                positions[position] -= 1
                yield comment
                break


def new_comments(
    current: Mapping[str, tuple[Sequence[Comment], set[int]]],
    previous: Iterable[Pool],
    retained: Set[tuple[str, Comment]] = frozenset(),
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
            if surplus[comment.key] <= 0 or (path, comment) in retained:
                continue
            if any(line in added for line in comment.lines):
                found.append((path, comment))
                surplus[comment.key] -= 1
    return found
