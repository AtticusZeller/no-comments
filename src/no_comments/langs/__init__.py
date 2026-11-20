from dataclasses import dataclass


@dataclass(frozen=True)
class Comment:
    line: int
    col: int
    text: str


class ParseError(Exception):
    pass
