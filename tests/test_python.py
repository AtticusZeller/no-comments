import re
from pathlib import Path

import pytest

from no_comments.allow import is_allowed
from no_comments.cli import main
from no_comments.langs import Comment, ParseError
from no_comments.langs.python import extract

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_positions():
    source = "x = 1\n# full line\ny = f(x)  # trailing\n"
    assert extract(source) == [
        Comment(2, 1, "# full line"),
        Comment(3, 11, "# trailing"),
    ]


def test_hash_inside_strings_is_not_a_comment():
    assert extract((FIXTURES / "strings.py").read_text()) == []


def test_syntax_error_raises_parse_error():
    with pytest.raises(ParseError):
        extract('x = """unterminated\n# c\n')


@pytest.mark.parametrize(
    "line, text",
    [
        (1, "#!/usr/bin/env python3"),
        (1, "# -*- coding: utf-8 -*-"),
        (2, "# vim: set fileencoding=utf-8 :"),
        (5, "# noqa: E501"),
        (5, "# type: ignore"),
        (5, "# pyright: ignore[reportGeneralTypeIssues]"),
        (5, "# mypy: disable-error-code=misc"),
        (5, "# pragma: no cover"),
        (5, "# fmt: off"),
        (5, "# isort: skip"),
        (5, "# ruff: noqa"),
        (5, "# pylint: disable=invalid-name"),
        (5, "# KEEP: 硬件固件 bug，延时不可去掉"),
        (5, "# SPDX-License-Identifier: MIT"),
    ],
)
def test_default_allowed(line, text):
    assert is_allowed("python", Comment(line, 1, text))


@pytest.mark.parametrize(
    "line, col, text",
    [
        (5, 1, "# 修复 bug"),
        (2, 1, "#!/usr/bin/env python3"),
        (1, 5, "#!/usr/bin/env python3"),
        (3, 1, "# -*- coding: utf-8 -*-"),
        (5, 1, "# shellcheck disable=SC2086"),
        (5, 1, "# keep: lowercase is not the marker"),
    ],
)
def test_not_allowed(line, col, text):
    assert not is_allowed("python", Comment(line, col, text))


def test_extra_allow_patterns():
    extra = [re.compile(r"^TODO\(")]
    assert is_allowed("python", Comment(5, 1, "# TODO(bob): x"), extra)
    assert not is_allowed("python", Comment(5, 1, "# todo"), extra)


BASE = "#!/usr/bin/env python3\n# old comment\nx = 1\n\n\ndef f():\n    return x\n"


def test_new_comment_in_existing_file_is_reported(repo, capsys):
    repo.write("a.py", BASE)
    repo.commit()
    repo.stage("a.py", BASE.replace("x = 1\n", "x = 1\n# 修复 bug\n"))
    assert main(["check", "a.py"]) == 1
    out = capsys.readouterr().out
    assert "a.py:4:1: NC001 comment not allowed: # 修复 bug" in out
    assert "old comment" not in out


def test_existing_comments_on_untouched_lines_are_not_reported(repo, capsys):
    repo.write("a.py", BASE)
    repo.commit()
    repo.stage("a.py", BASE.replace("return x", "return x + 1"))
    assert main(["check", "a.py"]) == 0
    assert capsys.readouterr().out == ""


def test_strings_with_hash_are_not_reported(repo, capsys):
    repo.stage("strings.py", (FIXTURES / "strings.py").read_text())
    assert main(["check", "strings.py"]) == 0


def test_allowed_comments_are_not_reported(repo, capsys):
    source = (
        "#!/usr/bin/env python3\n"
        "# -*- coding: utf-8 -*-\n"
        "x = 'a' * 200  # noqa: E501\n"
        "y = f()  # type: ignore\n"
        "# KEEP: 硬件固件 bug，延时不可去掉\n"
        "sleep(0.1)\n"
    )
    repo.stage("a.py", source)
    assert main(["check", "a.py"]) == 0
    assert capsys.readouterr().out == ""


def test_all_comments_in_new_file_are_reported(repo, capsys):
    repo.write("base.py", "")
    repo.commit()
    repo.stage("new.py", "# one\nx = 1  # two\n\n# three\n")
    assert main(["check", "new.py"]) == 1
    lines = [s for s in capsys.readouterr().out.splitlines() if "NC001" in s]
    assert lines == [
        "new.py:1:1: NC001 comment not allowed: # one",
        "new.py:2:8: NC001 comment not allowed: # two",
        "new.py:4:1: NC001 comment not allowed: # three",
    ]


def test_syntax_error_warns_and_skips(repo, capsys):
    repo.stage("bad.py", 'x = """oops\n# c\n')
    repo.stage("ok.py", "x = 1\n")
    assert main(["check", "bad.py", "ok.py"]) == 0
    captured = capsys.readouterr()
    assert "bad.py" in captured.err
    assert captured.out == ""


def test_syntax_error_does_not_mask_other_violations(repo, capsys):
    repo.stage("bad.py", 'x = """oops\n')
    repo.stage("c.py", "# c\n")
    assert main(["check", "bad.py", "c.py"]) == 1
