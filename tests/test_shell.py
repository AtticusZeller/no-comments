from pathlib import Path

import pytest

from no_comments.allow import is_allowed
from no_comments.cli import main
from no_comments.langs import Comment
from no_comments.langs.shell import extract

FIXTURES = Path(__file__).parent / "fixtures"
TRICKY = (FIXTURES / "tricky.sh").read_text()


def test_extract_positions():
    source = 'echo "é"  # trailing\n  # indented\n'
    assert extract(source) == [Comment(1, 11, "# trailing"), Comment(2, 3, "# indented")]


def test_nested_comments_are_found():
    source = "f() {\n  if true; then\n    # deep\n    :\n  fi\n}\n"
    assert extract(source) == [Comment(3, 5, "# deep")]


def test_hash_outside_comments_is_ignored():
    assert extract(TRICKY) == [
        Comment(1, 1, "#!/usr/bin/env bash"),
        Comment(2, 1, "# shellcheck disable=SC2086"),
    ]


@pytest.mark.parametrize(
    "line, text",
    [(1, "#!/bin/sh"), (2, "# shellcheck disable=SC2086"), (9, "# KEEP: CI 镜像没有 GNU sed")],
)
def test_shell_allowed(line, text):
    assert is_allowed("shell", Comment(line, 1, text))


@pytest.mark.parametrize("text", ["# noqa", "# type: ignore", "# 启动服务"])
def test_shell_not_allowed(text):
    assert not is_allowed("shell", Comment(4, 1, text))


BASE = "#!/bin/bash\nset -e\nmake build\n"


def test_new_comment_is_reported(repo, capsys):
    repo.write("run.sh", BASE)
    repo.commit()
    repo.stage("run.sh", BASE + "# 启动服务\n./serve\n")
    assert main(["check", "run.sh"]) == 1
    assert "run.sh:4:1: NC001 comment not allowed: # 启动服务" in capsys.readouterr().out


def test_tricky_new_file_passes(repo, capsys):
    repo.stage("tricky.sh", TRICKY)
    assert main(["check", "tricky.sh"]) == 0
    assert capsys.readouterr().out == ""


def test_bash_extension(repo, capsys):
    repo.stage("lib.bash", "# 启动服务\n")
    assert main(["check", "lib.bash"]) == 1


def test_shellcheck_with_trailing_narrative_is_reported(repo, capsys):
    repo.stage("run.sh", "echo $x  # shellcheck disable=SC2086  # 修复 bug\n")
    assert main(["check", "run.sh"]) == 1
    out = capsys.readouterr().out
    assert "run.sh:1:39: NC001 comment not allowed: # 修复 bug" in out
    assert "shellcheck disable" not in out.split("\n\n")[0]
