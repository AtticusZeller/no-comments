import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from no_comments.cli import detect_language, main
from no_comments.report import HINT

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
    files = [str(p.relative_to(ROOT)) for d in ("src", "tests") for p in (ROOT / d).rglob("*.py")]
    files += [str(p.relative_to(ROOT)) for p in (ROOT / "tests").rglob("*.sh")]
    assert main(["audit", *files]) == 0
    assert capsys.readouterr().out == ""


PRE_COMMIT = shutil.which("pre-commit")
needs_pre_commit = pytest.mark.skipif(
    PRE_COMMIT is None or not (ROOT / ".git").exists(),
    reason="needs pre-commit on PATH and this repository checked out with git",
)


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
