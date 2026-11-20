import re
from dataclasses import dataclass
from enum import Enum

_MARKERS = re.compile(r"^[#\s]+")
_SEGMENT = re.compile(r"(?:\s{2,}|\s(?=#\s))(?=#)")


class Kind(Enum):
    COMMENT = "comment"
    DOCSTRING = "docstring"


@dataclass(frozen=True)
class Comment:
    line: int
    col: int
    text: str
    kind: Kind = Kind.COMMENT
    content: str = ""
    end_line: int = 0

    @property
    def body(self) -> str:
        if self.kind is Kind.DOCSTRING:
            return self.content
        return _MARKERS.sub("", self.text).rstrip()

    @property
    def lines(self) -> range:
        return range(self.line, max(self.line, self.end_line) + 1)

    @property
    def key(self) -> tuple[Kind, str]:
        return self.kind, self.body


def comment_segments(line: int, col: int, text: str) -> list[Comment]:
    starts = [0]
    for match in _SEGMENT.finditer(text):
        if _MARKERS.fullmatch(text[starts[-1] : match.start()]) is None:
            starts.append(match.end())
    ends = starts[1:] + [len(text)]
    return [
        Comment(line, col + start, text[start:end].rstrip())
        for start, end in zip(starts, ends, strict=True)
    ]


class ParseError(Exception):
    pass
