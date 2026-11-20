import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from no_comments.cli import detect_language, main
from no_comments.report import HINT, SHAPE_HINT

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "name, content, expected",
    [
        ("a.py", "", "python"),
        ("a.pyi", "", "python"),
        ("a.sh", "", "shell"),
        ("a.bash", "", "shell"),
        ("a.js", "// x\n", None),
        ("a.yaml", "# x\n", None),
        ("Dockerfile", "# x\n", None),
        ("tool", "#!/usr/bin/env python3\n", "python"),
        ("tool", "#!/usr/bin/python3.12 -u\n", "python"),
        ("tool", "#!/bin/bash\n", "shell"),
        ("tool", "#!/usr/bin/env -S bash -e\n", "shell"),
        ("tool", "#!/bin/sh\n", "shell"),
        ("tool", "#!/usr/bin/env node\n", None),
        ("tool", "plain text\n", None),
        ("deploy.prod", "#!/bin/bash\n", "shell"),
        ("run.local", "#!/usr/bin/env python3\n", "python"),
        ("notes.txt", "plain\n", None),
    ],
)
def test_detect_language(tmp_path, name, content, expected):
    path = tmp_path / name
    path.write_text(content)
    assert detect_language(path) == expected


def test_missing_file_is_skipped(repo):
    assert main(["check", "gone.py"]) == 0


def test_output_format_and_hint(repo, capsys):
    long = "# " + "x" * 100
    repo.stage("a.py", f"x = 1  # trailing\n{long}\n")
    assert main(["check", "a.py"]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "a.py:1:8: NC001 comment not allowed: # trailing",
        f"a.py:2:1: NC001 comment not allowed: {long[:60]}",
        "",
        HINT,
    ]


def test_unsupported_files_are_ignored(repo, capsys):
    repo.stage("config.yaml", "# yaml comment\n")
    repo.stage("app.js", "// js comment\n")
    assert main(["check", "config.yaml", "app.js"]) == 0


def test_shebang_script_without_extension(repo, capsys):
    repo.stage("bin/tool", "#!/usr/bin/env python3\n# 新增\n")
    assert main(["check", "bin/tool"]) == 1
    assert "bin/tool:2:1: NC001" in capsys.readouterr().out


def test_allow_option(repo, capsys):
    repo.stage("a.py", "# TODO(bob): later\n# other\n")
    assert main(["check", "--allow", r"^TODO\(", "--allow", "^other$", "a.py"]) == 0


def test_invalid_allow_regex_exits_2(repo, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["check", "--allow", "(", "a.py"])
    assert exc.value.code == 2


def test_no_files_passes(repo):
    assert main(["check"]) == 0


def test_not_in_git_repo_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "a.py").write_text("# c\n")
    assert main(["check", "a.py"]) == 2
    assert "error" in capsys.readouterr().err


def test_range_mode_reports_only_comments_added_in_range(repo, capsys, monkeypatch):
    repo.write("a.py", "# old\nx = 1\n")
    repo.commit()
    repo.write("a.py", "# old\nx = 1\n# before range\n")
    start = repo.commit()
    repo.write("a.py", "# old\nx = 1\n# before range\n# in range\n")
    repo.write("b.py", "# new file in range\n")
    end = repo.commit()
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", start)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", end)
    assert main(["check", "a.py", "b.py"]) == 1
    out = capsys.readouterr().out
    assert "a.py:4:1: NC001 comment not allowed: # in range" in out
    assert "b.py:1:1: NC001" in out
    assert "old" not in out
    assert "before range" not in out


def test_range_mode_on_diverged_branches(repo, capsys, monkeypatch):
    repo.write("a.py", "x = 1\ny = 2\nz = 3\n")
    base = repo.commit()
    repo.write("a.py", "# main note\nx = 1\ny = 2\nz = 3\n")
    repo.commit()
    repo.git("checkout", "-q", "-b", "feature", base)
    repo.write("a.py", "x = 1\ny = 2\nz = 3\n# feature note\n")
    repo.commit()
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "main")
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "feature")
    assert main(["check", "a.py"]) == 1
    out = capsys.readouterr().out
    assert "a.py:4:1: NC001 comment not allowed: # feature note" in out
    assert "main note" not in out


def test_merge_conflict_resolution_keeps_incoming_comments(repo, capsys):
    repo.write("a.py", "x = 1\n")
    base = repo.commit()
    repo.git("checkout", "-q", "-b", "feature", base)
    repo.write("a.py", "x = 2\n# from feature\n")
    repo.commit()
    repo.git("checkout", "-q", "main")
    repo.write("a.py", "x = 3\n")
    repo.commit()
    merge = subprocess.run(["git", "merge", "feature"], cwd=repo.root, capture_output=True)
    assert merge.returncode != 0
    repo.stage("a.py", "x = 3\n# from feature\n")
    assert main(["check", "a.py"]) == 0, capsys.readouterr().out


def test_non_utf8_file_warns_and_passes(repo, capsys):
    (repo.root / "a.py").write_bytes(b"x = '\xe9'\n# c\n")
    repo.git("add", "a.py")
    assert main(["check", "a.py"]) == 0
    assert "a.py" in capsys.readouterr().err


def test_audit_lists_all_comments_and_exits_0(repo, capsys):
    repo.write("a.py", "#!/usr/bin/env python3\n# old\nx = 1  # noqa\n")
    repo.write("pkg/b.sh", "#!/bin/sh\n# start\n")
    repo.write("notes.yaml", "# yaml\n")
    repo.commit()
    repo.stage("a.py", "#!/usr/bin/env python3\n# old\nx = 1  # noqa\n# new\n")
    assert main(["audit"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "a.py:2:1: NC001 comment not allowed: # old",
        "a.py:4:1: NC001 comment not allowed: # new",
        "pkg/b.sh:2:1: NC001 comment not allowed: # start",
    ]
    assert main(["audit", "pkg"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "pkg/b.sh:2:1: NC001 comment not allowed: # start",
    ]
    assert main(["audit", "a.py"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2


def test_repository_source_has_no_comments(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    sample = ROOT / "tests" / "fixtures" / "cleanup"
    paths = [
        p
        for d in ("src", "tests", "scripts", "skills")
        for pattern in ("*.py", "*.sh")
        for p in (ROOT / d).rglob(pattern)
        if sample not in p.parents
    ]
    assert any(p.suffix == ".sh" and "skills" in p.parts for p in paths)
    files = [str(p.relative_to(ROOT)) for p in paths]
    assert main(["audit", *files]) == 0
    assert capsys.readouterr().out == ""


PRE_COMMIT = shutil.which("pre-commit")
needs_pre_commit = pytest.mark.skipif(
    PRE_COMMIT is None or not (ROOT / ".git").exists(),
    reason="needs pre-commit on PATH and this repository checked out with git",
)


@pytest.mark.skipif(not os.environ.get("CI"), reason="only enforced in CI")
def test_ci_runs_integration_tests():
    assert PRE_COMMIT is not None, "pre-commit must be on PATH in CI"
    assert (ROOT / ".git").exists(), "CI must check out the repository with git"


@pytest.fixture(scope="session")
def pre_commit_home(tmp_path_factory):
    return tmp_path_factory.mktemp("pre-commit-home")


def pre_commit(repo, home, *args):
    assert PRE_COMMIT is not None
    env = {**os.environ, "PRE_COMMIT_HOME": str(home)}
    return subprocess.run(
        [PRE_COMMIT, *args], cwd=repo.root, env=env, capture_output=True, text=True
    )


@needs_pre_commit
def test_try_repo_blocks_violation_then_passes(repo, pre_commit_home):
    repo.write("a.py", "x = 1\n")
    repo.commit()
    repo.stage("a.py", "x = 1\n# 修复 bug\n")
    result = pre_commit(repo, pre_commit_home, "try-repo", str(ROOT), "no-comments")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "a.py:2:1: NC001 comment not allowed: # 修复 bug" in result.stdout
    assert HINT in result.stdout
    repo.stage("a.py", "x = 1\ny = 2\n")
    result = pre_commit(repo, pre_commit_home, "try-repo", str(ROOT), "no-comments")
    assert result.returncode == 0, result.stdout + result.stderr


@needs_pre_commit
def test_try_repo_ref_range(repo, pre_commit_home):
    repo.write("a.py", "# old\nx = 1\n")
    start = repo.commit()
    repo.write("a.py", "# old\nx = 1\n# in range\n")
    end = repo.commit()
    result = pre_commit(
        repo,
        pre_commit_home,
        "try-repo",
        str(ROOT),
        "no-comments",
        "--from-ref",
        start,
        "--to-ref",
        end,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "a.py:3:1: NC001 comment not allowed: # in range" in result.stdout
    assert "# old" not in result.stdout


@needs_pre_commit
def test_installed_hook_blocks_commit(repo, pre_commit_home):
    exe = shlex.quote(str(Path(sys.executable).parent / "no-comments"))
    repo.write(
        ".pre-commit-config.yaml",
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: no-comments\n"
        "        name: no-comments\n"
        f"        entry: {exe} check\n"
        "        language: system\n"
        "        types_or: [python, pyi, shell]\n",
    )
    repo.write("a.py", "x = 1\n")
    repo.commit()
    assert pre_commit(repo, pre_commit_home, "install").returncode == 0
    repo.stage("a.py", "x = 1\n# 修复 bug\n")
    blocked = subprocess.run(
        ["git", "commit", "-m", "add"], cwd=repo.root, capture_output=True, text=True
    )
    assert blocked.returncode != 0
    assert "NC001" in blocked.stdout + blocked.stderr
    repo.stage("a.py", "x = 1\ny = 2\n")
    passed = subprocess.run(
        ["git", "commit", "-m", "add"], cwd=repo.root, capture_output=True, text=True
    )
    assert passed.returncode == 0, passed.stdout + passed.stderr


def test_audit_allow_option(repo, capsys):
    repo.write("a.py", "# TODO(bob): later\n# other\n")
    assert main(["audit", "--allow", r"^TODO\(", "a.py"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "a.py:2:1: NC001 comment not allowed: # other",
    ]


FUNC = "def f():\n    # explain f\n    return 1\n\n\ndef g():\n    return 2\n"


def test_rename_without_changes_passes(repo):
    repo.write("old.py", FUNC)
    repo.commit()
    repo.git("mv", "old.py", "new.py")
    assert main(["check", "new.py"]) == 0


def test_rename_reports_only_the_added_comment(repo, capsys):
    repo.write("old.py", FUNC)
    repo.commit()
    repo.git("mv", "old.py", "new.py")
    repo.stage("new.py", FUNC + "\n\n# added\n")
    assert main(["check", "new.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == ["new.py:10:1: NC001 comment not allowed: # added"]


def test_rename_where_git_sees_new_file_still_compares_whole_file(repo):
    repo.write("old.py", "# one\n")
    repo.commit()
    repo.git("mv", "old.py", "new.py")
    repo.stage("new.py", "# one\nx = 1\n")
    assert main(["check", "new.py"]) == 0


def test_changing_code_before_trailing_comment_passes(repo):
    repo.write("a.py", "x = 1  # note\n")
    repo.commit()
    repo.stage("a.py", "x = 2  # note\n")
    assert main(["check", "a.py"]) == 0


def test_changing_trailing_comment_text_is_reported(repo, capsys):
    repo.write("a.py", "x = 1  # note\n")
    repo.commit()
    repo.stage("a.py", "x = 1  # other\n")
    assert main(["check", "a.py"]) == 1
    assert "a.py:1:8: NC001 comment not allowed: # other" in capsys.readouterr().out


def test_moving_a_commented_function_passes(repo):
    repo.write("a.py", FUNC)
    repo.commit()
    moved = "def g():\n    return 2\n\n\ndef f():\n    # explain f\n    return 1\n"
    repo.stage("a.py", moved)
    assert main(["check", "a.py"]) == 0


def test_duplicate_of_existing_comment_text_is_reported(repo, capsys):
    repo.write("a.py", "# same\nx = 1\n")
    repo.commit()
    repo.stage("a.py", "# same\nx = 1\n# same\ny = 2\n")
    assert main(["check", "a.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == ["a.py:3:1: NC001 comment not allowed: # same"]


def test_identical_text_replacing_a_removed_comment_is_not_reported(repo):
    repo.write("a.py", "# same\nx = 1\ny = 2\n")
    repo.commit()
    repo.stage("a.py", "x = 1\ny = 2\n# same\n")
    assert main(["check", "a.py"]) == 0


def test_range_mode_rename(repo, capsys, monkeypatch):
    repo.write("old.py", FUNC)
    start = repo.commit()
    repo.git("mv", "old.py", "new.py")
    repo.write("new.py", FUNC + "\n\n# added in range\n")
    end = repo.commit()
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", start)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", end)
    assert main(["check", "new.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == ["new.py:10:1: NC001 comment not allowed: # added in range"]


def test_comment_written_while_resolving_merge_is_reported(repo, capsys):
    repo.write("a.py", "x = 1\n")
    base = repo.commit()
    repo.git("checkout", "-q", "-b", "feature", base)
    repo.write("a.py", "x = 2\n# from feature\n")
    repo.commit()
    repo.git("checkout", "-q", "main")
    repo.write("a.py", "x = 3\n")
    repo.commit()
    subprocess.run(["git", "merge", "feature"], cwd=repo.root, capture_output=True)
    repo.stage("a.py", "x = 3\n# from feature\n# while resolving\n")
    assert main(["check", "a.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == ["a.py:3:1: NC001 comment not allowed: # while resolving"]


MOVED = 'def moved():\n    """Moved doc."""\n    # explain moved\n    return 1\n'
SPLIT_SOURCE = "def keep():\n    return 0\n\n\n" + MOVED


def test_function_split_into_new_file_passes(repo):
    repo.write("big.py", SPLIT_SOURCE)
    repo.commit()
    repo.stage("big.py", "def keep():\n    return 0\n")
    repo.stage(
        "small.py", 'def moved():\n    """Moved doc."""\n    # explain moved\n    return 1\n'
    )
    assert main(["check", "big.py", "small.py"]) == 0


def test_split_with_one_new_comment_reports_only_it(repo, capsys):
    repo.write("big.py", SPLIT_SOURCE)
    repo.commit()
    repo.stage("big.py", "def keep():\n    return 0\n")
    repo.stage(
        "small.py",
        'def moved():\n    """Moved doc."""\n    # explain moved\n    # brand new\n    return 1\n',
    )
    assert main(["check", "small.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == ["small.py:4:5: NC001 comment not allowed: # brand new"]


def test_rename_with_heavy_rewrite_keeps_old_comments(repo):
    repo.write("old.py", "# keep me\nx = 1\ny = 2\n")
    repo.commit()
    repo.git("rm", "-q", "old.py")
    repo.stage("new.py", "# keep me\na = 10\nb = 20\nc = 30\n")
    assert main(["check", "new.py"]) == 0


def test_move_into_file_deleted_in_same_change_range_mode(repo, monkeypatch):
    repo.write("a.py", "def f():\n    # from a\n    return 1\n")
    start = repo.commit()
    repo.git("rm", "-q", "a.py")
    repo.write("b.py", "def f():\n    # from a\n    return 1\n\n\ndef g():\n    return 2\n")
    end = repo.commit()
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", start)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", end)
    assert main(["check", "b.py"]) == 0


def test_narrative_after_pragma_is_reported(repo, capsys):
    repo.stage("a.py", "x = f()  # noqa  # 修复 bug\ny = g()  # type: ignore #修复\n")
    assert main(["check", "a.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == [
        "a.py:1:18: NC001 comment not allowed: # 修复 bug",
        "a.py:2:10: NC001 comment not allowed: # type: ignore #修复",
    ]


def test_ty_directives_pass_and_narrative_after_them_is_reported(repo, capsys):
    repo.stage(
        "a.py",
        "# ty: ignore[invalid-argument-type]\n\n"
        'x = 10 + "x"  # ty: ignore[unsupported-operator]\n'
        "y = f()  # ty: ignore[call-non-callable]  # 修复 bug\n"
        "z = g()  # ty: ignore #修复\n",
    )
    assert main(["check", "a.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == [
        "a.py:4:43: NC001 comment not allowed: # 修复 bug",
        "a.py:5:10: NC001 comment not allowed: # ty: ignore #修复",
    ]


def test_dropping_pragma_before_existing_note_passes(repo):
    repo.write("a.py", "ok = isinstance(x, str)  # type: ignore[misc]  # runtime guard\n")
    repo.commit()
    repo.stage("a.py", "ok = isinstance(x, str)  # runtime guard\n")
    assert main(["check", "a.py"]) == 0


def test_uncommenting_code_keeps_inner_comments(repo):
    repo.write("a.py", "def f():\n    return 1\n#     # Create items\n#     items = []\n")
    repo.commit()
    repo.stage("a.py", "def f():\n    return 1\n    # Create items\n    items = []\n")
    assert main(["check", "a.py"]) == 0


def test_new_nested_comment_text_is_reported(repo, capsys):
    repo.write("a.py", "x = 1\n")
    repo.commit()
    repo.stage("a.py", "x = 1\n#   # 新说明\n")
    assert main(["check", "a.py"]) == 1
    assert "a.py:2:1: NC001 comment not allowed: #   # 新说明" in capsys.readouterr().out


def test_unrelated_large_files_are_not_diffed(repo, monkeypatch):
    from no_comments import diff

    calls = []
    real_git = diff.git
    monkeypatch.setattr(diff, "git", lambda *a: calls.append(a) or real_git(*a))
    repo.write("a.py", "x = 1\n")
    repo.write("vendor.js", "a\n" * 1000)
    repo.commit()
    repo.stage("a.py", "x = 2\n")
    repo.stage("vendor.js", "b\n" * 1000)
    assert main(["check", "a.py"]) == 0
    content_diff = [c for c in calls if "-U0" in c]
    assert content_diff and "vendor.js" not in content_diff[0] and "a.py" in content_diff[0]


@pytest.mark.parametrize(
    "comment",
    [
        "# (V, 3, 10)",
        "# [1, H, W, 3]",
        "# (B, T, D) after projection",
        "# (*batch, 3)",
        "# (num_envs,)",
        "# (V', 3, K)",
        "# (B, J + 1, 4, 4)",
        "# (*, 55*3*3)",
    ],
)
def test_shape_comment_adds_jaxtyping_hint(repo, capsys, comment):
    repo.stage("a.py", f"x = f()  {comment}\n")
    assert main(["check", "a.py"]) == 1
    out = capsys.readouterr().out
    assert "NC001" in out
    assert out.rstrip().endswith(SHAPE_HINT)


@pytest.mark.parametrize("comment", ["# (see issue 12)", "# [TODO]", "# (B)", "# [-pi, pi]"])
def test_other_comments_have_no_shape_hint(repo, capsys, comment):
    repo.stage("a.py", f"x = f()  {comment}\n")
    assert main(["check", "a.py"]) == 1
    assert SHAPE_HINT not in capsys.readouterr().out


def test_shape_hint_printed_once(repo, capsys):
    repo.stage("a.py", "x = f()  # (B, N, 3)\n# 修复 bug\ny = g()  # [B, H, W]\n")
    repo.stage("b.py", "z = h()  # (T, D)\n")
    assert main(["check", "a.py", "b.py"]) == 1
    out = capsys.readouterr().out
    assert out.count(SHAPE_HINT) == 1
    assert out.count("NC001") == 4


def test_shape_docstring_has_no_shape_hint(repo, capsys):
    repo.stage("a.py", '"""(B, N, 3)"""\n')
    assert main(["check", "a.py"]) == 1
    assert SHAPE_HINT not in capsys.readouterr().out
