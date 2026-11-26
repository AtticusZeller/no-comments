from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping, Sequence, Set

from no_comments.diff import Replacement
from no_comments.langs import Comment, Kind

Key = tuple[Kind, str]
Pool = Counter[Key]


def pool(versions: Iterable[Sequence[Comment]]) -> Pool:
    return Counter(c.key for comments in versions for c in comments)


def _in_ranges(comments: Sequence[Comment], ranges: Iterable[range]) -> Iterator[Sequence[Comment]]:
    start = end = 0
    for lines in ranges:
        while start < len(comments) and comments[start].lines.stop <= lines.start:
            start += 1
        end = max(start, end)
        while end < len(comments) and comments[end].line < lines.stop:
            end += 1
        yield comments[start:end]


def retained_comments(
    old: Sequence[Comment], new: Sequence[Comment], replaced: Sequence[Replacement]
) -> set[Comment]:
    old_groups = _in_ranges(old, (before for before, _ in replaced))
    new_groups = _in_ranges(new, (after for _, after in replaced))
    used: set[Comment] = set()
    retained: set[Comment] = set()
    for before, after in zip(old_groups, new_groups, strict=True):
        by_key: dict[Key, deque[Comment]] = defaultdict(deque)
        for candidate in before:
            if candidate not in used:
                by_key[candidate.key].append(candidate)
        for comment in after:
            candidates = by_key.get(comment.key)
            if candidates and comment not in retained:
                used.add(candidates.popleft())
                retained.add(comment)
    return retained


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
