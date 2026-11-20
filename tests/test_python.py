import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from no_comments.allow import is_allowed
from no_comments.cli import main
from no_comments.langs import Comment, Kind, ParseError
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


DOCSTRINGS = '''\
"""Module doc."""


class A:
    """Class doc."""

    def m(self):
        """Method doc."""
        x = 1
        """Pretend comment."""
        return x


async def run():
    """Async doc."""
'''


def test_extract_docstrings():
    docs = [c for c in extract(DOCSTRINGS) if c.kind is Kind.DOCSTRING]
    assert [(c.line, c.col, c.body) for c in docs] == [
        (1, 1, "Module doc."),
        (5, 5, "Class doc."),
        (8, 9, "Method doc."),
        (10, 9, "Pretend comment."),
        (15, 5, "Async doc."),
    ]


def test_new_docstrings_are_reported(repo, capsys):
    repo.stage("a.py", DOCSTRINGS)
    assert main(["check", "a.py"]) == 1
    out = [s for s in capsys.readouterr().out.splitlines() if "NC00" in s]
    assert out == [
        'a.py:1:1: NC002 docstring not allowed: """Module doc."""',
        'a.py:5:5: NC002 docstring not allowed: """Class doc."""',
        'a.py:8:9: NC002 docstring not allowed: """Method doc."""',
        'a.py:10:9: NC002 docstring not allowed: """Pretend comment."""',
        'a.py:15:5: NC002 docstring not allowed: """Async doc."""',
    ]


def test_strings_that_are_not_statements_are_ignored():
    source = 'x = """text"""\nf"standalone {x}"\nb"bytes"\nprint("""arg""")\n'
    assert [c for c in extract(source) if c.kind is Kind.DOCSTRING] == []


def test_keep_docstring_is_allowed(repo):
    repo.stage("a.py", 'def f():\n    """\n    KEEP: 下游解析器依赖这段文本\n    """\n')
    assert main(["check", "a.py"]) == 0


def test_allow_option_applies_to_docstrings(repo):
    repo.stage("a.py", '"""Usage: tool [ARGS]"""\n')
    assert main(["check", "--allow", "^Usage:", "a.py"]) == 0


def test_multiline_docstring_reported_when_any_line_is_added(repo, capsys):
    repo.write("a.py", 'def f():\n    """First.\n\n    Old detail.\n    """\n')
    repo.commit()
    repo.stage("a.py", 'def f():\n    """First.\n\n    New detail.\n    """\n')
    assert main(["check", "a.py"]) == 1
    assert 'a.py:2:5: NC002 docstring not allowed: """First.' in capsys.readouterr().out


def test_unchanged_docstring_with_changed_body_passes(repo):
    repo.write("a.py", 'def f():\n    """Doc."""\n    return 1\n')
    repo.commit()
    repo.stage("a.py", 'def f():\n    """Doc."""\n    return 2\n')
    assert main(["check", "a.py"]) == 0


def test_reindented_docstring_passes(repo):
    repo.write("a.py", 'def f():\n    """Doc.\n\n    More.\n    """\n')
    repo.commit()
    repo.stage(
        "a.py", 'class A:\n    def f(self):\n        """Doc.\n\n        More.\n        """\n'
    )
    assert main(["check", "a.py"]) == 0


def test_audit_lists_docstrings(repo, capsys):
    repo.write("a.py", 'def f():\n    """Doc."""\n')
    assert main(["audit", "a.py"]) == 0
    assert capsys.readouterr().out == 'a.py:2:5: NC002 docstring not allowed: """Doc."""\n'


def test_ast_syntax_error_warns_and_skips(repo, capsys):
    repo.stage("bad.py", "def f(:\n    pass\n# c\n")
    assert main(["check", "bad.py"]) == 0
    assert "bad.py" in capsys.readouterr().err


def test_comment_segments():
    assert [(c.col, c.text) for c in extract("x = f()  # noqa  # 修复 bug\n")] == [
        (10, "# noqa"),
        (18, "# 修复 bug"),
    ]
    assert [c.text for c in extract("# 颜色 #fff\n# 见 issue #123\n")] == [
        "# 颜色 #fff",
        "# 见 issue #123",
    ]
    assert [c.body for c in extract("#             # NOTE:RMSE\n")] == ["NOTE:RMSE"]


@pytest.mark.parametrize("warnings_env", ["default", "error"])
def test_invalid_escape_does_not_warn(repo, warnings_env):
    repo.stage("a.py", 'x = "\\["\n# c\n')
    exe = Path(sys.executable).parent / "no-comments"
    env = {**os.environ, "PYTHONWARNINGS": warnings_env}
    result = subprocess.run(
        [str(exe), "check", "a.py"], cwd=repo.root, env=env, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "a.py:2:1: NC001" in result.stdout
    assert result.stderr == ""
