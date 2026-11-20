from no_comments.compare import new_comments
from no_comments.langs import Comment, Kind


def c(line, text, kind=Kind.COMMENT, end_line=0):
    return Comment(line, 1, text, kind, text if kind is Kind.DOCSTRING else "", end_line)


def test_comment_on_unchanged_line_is_never_new():
    assert new_comments([c(1, "# a")], [], {2}) == []


def test_new_text_on_added_line():
    assert new_comments([c(1, "# a"), c(2, "# b")], [[c(1, "# a")]], {2}) == [c(2, "# b")]


def test_surplus_is_reported_in_file_order():
    current = [c(1, "# a"), c(2, "# a"), c(3, "# a")]
    assert new_comments(current, [[c(1, "# a")]], {2, 3}) == [c(2, "# a"), c(3, "# a")]
    assert new_comments(current, [[c(1, "# a"), c(5, "# a")]], {2, 3}) == [c(2, "# a")]


def test_previous_versions_are_combined_by_max_count():
    current = [c(1, "# a"), c(2, "# a"), c(3, "# b")]
    ours = [c(1, "# a")]
    theirs = [c(1, "# a"), c(2, "# a"), c(3, "# b")]
    assert new_comments(current, [ours, theirs], {1, 2, 3}) == []


def test_comment_and_docstring_with_same_text_are_distinct():
    current = [c(1, "a", Kind.DOCSTRING)]
    assert new_comments(current, [[c(1, "# a")]], {1}) == current


def test_multiline_item_counts_if_any_line_is_added():
    doc = c(1, "a", Kind.DOCSTRING, end_line=3)
    assert new_comments([doc], [], {3}) == [doc]
