import pytest

from no_comments.diff import (
    FileDiff,
    GitError,
    base_revisions,
    changed_paths,
    collect_changes,
    diff_range,
    parse_diff,
    read_blobs,
    unquote,
)

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


def by_new_path(refs=None):
    return {c.new_path: c for c in collect_changes(refs)}


def added(path, refs=None):
    change = by_new_path(refs).get(path)
    return set() if change is None else change.added


def test_parse_multiple_hunks_and_pure_deletion():
    assert parse_diff(MULTI_HUNK) == [FileDiff("a.py", "a.py", {2, 3, 12})]


def test_parse_new_file():
    text = "diff --git a/n.py b/n.py\n--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,3 @@\n+a\n+b\n+c\n"
    assert parse_diff(text) == [FileDiff(None, "n.py", {1, 2, 3})]


def test_parse_deleted_file_keeps_old_path():
    text = "diff --git a/d.py b/d.py\n--- a/d.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    assert parse_diff(text) == [FileDiff("d.py", None)]


def test_parse_rename_with_changes():
    text = (
        "diff --git a/old name.py b/new name.py\n"
        "similarity index 90%\n"
        "rename from old name.py\n"
        "rename to new name.py\n"
        "--- a/old name.py\t\n"
        "+++ b/new name.py\t\n"
        "@@ -3,0 +4 @@\n"
        "+z\n"
    )
    assert parse_diff(text) == [FileDiff("old name.py", "new name.py", {4})]


def test_parse_quoted_paths():
    text = (
        'diff --git "a/t\\tab.py" "b/t\\tab.py"\n'
        "--- /dev/null\n"
        '+++ "b/t\\tab\\"q\\\\\\303\\251.py"\n'
        "@@ -0,0 +1 @@\n"
        "+x\n"
    )
    assert parse_diff(text) == [FileDiff(None, 't\tab"q\\é.py', {1})]


def test_parse_ignores_content_lines_that_look_like_headers():
    text = (
        "diff --git a/a.sql b/a.sql\n--- a/a.sql\n+++ b/a.sql\n"
        "@@ -1 +1 @@\n--- removed sql comment\n+++ added\n"
        "@@ -5 +5,0 @@\n-x\n+@@ -0,0 +9,9 @@\n"
    )
    assert parse_diff(text) == [FileDiff("a.sql", "a.sql", {1})]


def test_unquote_plain_path():
    assert unquote("a b.py") == "a b.py"


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
    assert added("a.py") == {2, 5}


def test_unstaged_changes_are_ignored(repo):
    repo.write("a.py", "a\n")
    repo.commit()
    repo.write("a.py", "a\nb\n")
    assert added("a.py") == set()


def test_staged_new_file_is_fully_added(repo):
    repo.write("base.py", "")
    repo.commit()
    repo.stage("new.py", "1\n2\n3\n")
    assert by_new_path()["new.py"] == FileDiff(None, "new.py", {1, 2, 3})


def test_staged_pure_deletion(repo):
    repo.write("a.py", "a\nb\nc\n")
    repo.commit()
    repo.stage("a.py", "a\nc\n")
    assert added("a.py") == set()


@pytest.mark.parametrize("name", ["with space.py", "glob [1]*.py", "dir x/y z.py", "t\tab.py"])
def test_special_file_names(repo, name):
    repo.write("base.py", "")
    repo.commit()
    repo.stage(name, "a\nb\n")
    repo.stage("glob 11.py", "other\n")
    assert added(name) == {1, 2}


def test_staged_rename(repo):
    repo.write("old.py", "a\nb\nc\nd\ne\n")
    repo.commit()
    repo.git("mv", "old.py", "new.py")
    repo.stage("new.py", "a\nb\nc\nd\ne\nf\n")
    assert by_new_path()["new.py"] == FileDiff("old.py", "new.py", {6})


def test_commit_range(repo):
    repo.write("a.py", "a\n")
    first = repo.commit()
    repo.write("a.py", "a\nb\n")
    repo.commit()
    repo.write("a.py", "a\nb\nc\n")
    last = repo.commit()
    repo.stage("a.py", "a\nb\nc\nd\n")
    assert added("a.py", (first, last)) == {2, 3}


def test_staged_file_before_first_commit(repo):
    repo.stage("a.py", "a\nb\n")
    assert added("a.py") == {1, 2}
    assert base_revisions(None) == []


def test_base_revisions(repo):
    first = repo.commit()
    repo.commit()
    head = repo.git("rev-parse", "HEAD")
    assert base_revisions(None) == ["HEAD"]
    assert base_revisions((first, head)) == [first]


def test_read_blobs(repo):
    repo.write("a.py", "x = 1\n")
    repo.write("b c.py", "y = 2\n")
    repo.write("bin.dat", "")
    (repo.root / "bin.dat").write_bytes(b"\xff\xfe")
    repo.commit()
    assert read_blobs("HEAD", ["a.py", "missing.py", "b c.py", "bin.dat"]) == {
        "a.py": "x = 1\n",
        "b c.py": "y = 2\n",
    }
    assert read_blobs("HEAD", []) == {}


def test_not_a_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(GitError):
        collect_changes(None)


def test_only_relevant_files_are_diffed(repo):
    repo.write("a.py", "x = 1\n")
    repo.write("data.json", "{}\n")
    repo.commit()
    repo.stage("a.py", "x = 2\n")
    repo.stage("data.json", '{"a": 1}\n')
    changes = collect_changes(None, lambda p: p.endswith(".py"))
    assert changes == [FileDiff("a.py", "a.py", {1})]


def test_rename_survives_path_filtering(repo):
    repo.write("old.py", "a\nb\nc\nd\ne\n")
    repo.write("big.txt", "x\n")
    repo.commit()
    repo.git("mv", "old.py", "new.py")
    repo.stage("new.py", "a\nb\nc\nd\ne\nf\n")
    repo.stage("big.txt", "y\n")
    changes = collect_changes(None, lambda p: p.endswith(".py"))
    assert changes == [FileDiff("old.py", "new.py", {6})]


def test_changed_paths_statuses(repo):
    repo.write("m.py", "1\n")
    repo.write("d.py", "1\n")
    repo.write("r.py", "a\nb\nc\nd\n")
    repo.commit()
    repo.stage("m.py", "2\n")
    repo.git("rm", "-q", "d.py")
    repo.git("mv", "r.py", "s p.py")
    repo.stage("n.py", "new\n")
    assert sorted(changed_paths("--cached"), key=str) == sorted(
        [("m.py", "m.py"), ("d.py", None), ("r.py", "s p.py"), (None, "n.py")], key=str
    )
