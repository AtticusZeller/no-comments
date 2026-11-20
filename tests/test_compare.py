from no_comments.compare import new_comments, pool
from no_comments.langs import Comment, Kind


def c(line, text, kind=Kind.COMMENT, end_line=0):
    return Comment(line, 1, text, kind, text if kind is Kind.DOCSTRING else "", end_line)


def test_comment_on_unchanged_line_is_never_new():
    assert new_comments({"a.py": ([c(1, "# a")], {2})}, []) == []


def test_new_text_on_added_line():
    current = {"a.py": ([c(1, "# a"), c(2, "# b")], {2})}
    assert new_comments(current, [pool([[c(1, "# a")]])]) == [("a.py", c(2, "# b"))]


def test_surplus_is_reported_in_file_order():
    current = {"a.py": ([c(1, "# a"), c(2, "# a"), c(3, "# a")], {2, 3})}
    assert new_comments(current, [pool([[c(1, "# a")]])]) == [
        ("a.py", c(2, "# a")),
        ("a.py", c(3, "# a")),
    ]
    old = pool([[c(1, "# a"), c(5, "# a")]])
    assert new_comments(current, [old]) == [("a.py", c(2, "# a"))]


def test_comment_moved_to_another_file_is_not_new():
    current = {"a.py": ([], set()), "b.py": ([c(1, "# moved")], {1})}
    assert new_comments(current, [pool([[c(7, "# moved")]])]) == []


def test_surplus_is_shared_across_files_in_path_order():
    current = {"b.py": ([c(1, "# x")], {1}), "a.py": ([c(4, "# x")], {4})}
    assert new_comments(current, [pool([[c(1, "# x")]])]) == [("a.py", c(4, "# x"))]


def test_previous_versions_are_combined_by_max_count():
    current = {"a.py": ([c(1, "# a"), c(2, "# a"), c(3, "# b")], {1, 2, 3})}
    ours = pool([[c(1, "# a")]])
    theirs = pool([[c(1, "# a"), c(2, "# a"), c(3, "# b")]])
    assert new_comments(current, [ours, theirs]) == []


def test_comment_and_docstring_with_same_text_are_distinct():
    current = {"a.py": ([c(1, "a", Kind.DOCSTRING)], {1})}
    assert new_comments(current, [pool([[c(1, "# a")]])]) == [("a.py", c(1, "a", Kind.DOCSTRING))]


def test_multiline_item_counts_if_any_line_is_added():
    doc = c(1, "a", Kind.DOCSTRING, end_line=3)
    assert new_comments({"a.py": ([doc], {3})}, []) == [("a.py", doc)]
