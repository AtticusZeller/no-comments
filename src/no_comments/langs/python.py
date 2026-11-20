import io
import tokenize

from no_comments.langs import Comment, ParseError


def extract(source: str) -> list[Comment]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    try:
        return [
            Comment(tok.start[0], tok.start[1] + 1, tok.string)
            for tok in tokens
            if tok.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, SyntaxError) as exc:
        raise ParseError(str(exc)) from exc
