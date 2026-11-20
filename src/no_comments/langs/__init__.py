from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    COMMENT = "NC001 comment"
    DOCSTRING = "NC002 docstring"


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
        return self.text.lstrip("#").strip()

    @property
    def lines(self) -> range:
        return range(self.line, max(self.line, self.end_line) + 1)

    @property
    def key(self) -> tuple[Kind, str]:
        return self.kind, self.body


class ParseError(Exception):
    pass
