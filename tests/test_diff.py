import pytest

from no_comments.diff import GitError, added_lines, diff_range, parse_added_lines

MULTI_HUNK = """\
diff --git a/a.py b/a.py
index 1111111..2222222 100644
--- a/a.py
+++ b/a.py
@@ -1,0 +2,2 @@ def f():
+x = 1
+y = 2
@@ -10 +12 @@ def g():
-old
+new
@@ -20,3 +21,0 @@ def h():
-a
-b
-c
"""


def test_parse_multiple_hunks_and_pure_deletion():
    assert parse_added_lines(MULTI_HUNK) == {2, 3, 12}


def test_parse_new_file():
    text = "--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,3 @@\n+a\n+b\n+c\n"
    assert parse_added_lines(text) == {1, 2, 3}


def test_parse_ignores_content_lines_that_look_like_hunks():
    text = "@@ -1 +1 @@\n-x\n+@@ -0,0 +5,5 @@\n"
    assert parse_added_lines(text) == {1}


def test_parse_empty():
    assert parse_added_lines("") == set()


def test_diff_range_requires_both_refs(monkeypatch):
    assert diff_range() is None
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "a")
    assert diff_range() is None
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "b")
    assert diff_range() == ("a", "b")


def test_staged_changes(repo):
    repo.write("a.py", "a\nb\nc\nd\n")
    repo.commit()
    repo.stage("a.py", "a\nX\nc\nd\nY\n")
    assert added_lines("a.py", None) == {2, 5}


def test_unstaged_changes_are_ignored(repo):
    repo.write("a.py", "a\n")
    repo.commit()
    repo.write("a.py", "a\nb\n")
    assert added_lines("a.py", None) == set()


def test_staged_new_file_is_fully_added(repo):
    repo.write("base.py", "")
    repo.commit()
    repo.stage("new.py", "1\n2\n3\n")
    assert added_lines("new.py", None) == {1, 2, 3}


def test_staged_pure_deletion(repo):
    repo.write("a.py", "a\nb\nc\n")
    repo.commit()
    repo.stage("a.py", "a\nc\n")
    assert added_lines("a.py", None) == set()


@pytest.mark.parametrize("name", ["with space.py", "glob [1]*.py", "dir x/y z.py"])
def test_special_file_names(repo, name):
    repo.write("base.py", "")
    repo.commit()
    repo.stage(name, "a\nb\n")
    repo.stage("glob 11.py", "other\n")
    assert added_lines(name, None) == {1, 2}


def test_commit_range(repo):
    repo.write("a.py", "a\n")
    first = repo.commit()
    repo.write("a.py", "a\nb\n")
    repo.commit()
    repo.write("a.py", "a\nb\nc\n")
    last = repo.commit()
    repo.stage("a.py", "a\nb\nc\nd\n")
    assert added_lines("a.py", (first, last)) == {2, 3}


def test_not_a_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(GitError):
        added_lines("a.py", None)


def test_staged_file_before_first_commit(repo):
    repo.stage("a.py", "a\nb\n")
    assert added_lines("a.py", None) == {1, 2}
