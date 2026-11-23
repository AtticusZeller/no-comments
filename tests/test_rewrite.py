from pathlib import Path

import pytest

from no_comments.cli import main


def prepare(capsys, *rows):
    assert main(["audit"]) == 0
    Path("audit.txt").write_text(capsys.readouterr().out, encoding="utf-8")
    Path("review.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def run():
    return main(["strip", "review.txt", "--audit", "audit.txt"])


def test_strip_python_comments_by_segment(repo, capsys):
    path = repo.write(
        "a.py",
        "# obsolete\n# external limit\n\n"
        "é = 1  # obsolete inline  # constraint  # investigate   \n"
        "y = 2  # noqa  # obsolete last   \n"
        "z = 3  # encode\n",
    )
    repo.commit()
    prepare(
        capsys,
        "a.py:4:41 | WORKAROUND | investigate | evidence | -",
        "a.py:1:1 | DELETE | redundant | - | -",
        "a.py:4:8 | DELETE | redundant | - | -",
        "a.py:2:1 | KEEP | external | docs | # KEEP: external limit",
        "a.py:4:27 | KEEP | external | docs | # KEEP: external | constraint",
        "a.py:5:16 | DELETE | redundant | - | -",
        "a.py:6:8 | ENCODE | constraint | evidence | -",
    )
    assert run() == 0, capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == (
        "\n# KEEP: external limit\n# KEEP: external | constraint\n"
        "é = 1  # investigate\ny = 2  # noqa\nz = 3  # encode\n"
    )
    assert main(["verify-strip"]) == 0
    assert main(["audit", "a.py"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "a.py:4:8: NC001 comment not allowed: # investigate",
        "a.py:6:8: NC001 comment not allowed: # encode",
    ]


def test_strip_docstrings_uses_syntax_spans_and_keeps_empty_suites_valid(repo, capsys):
    path = repo.write(
        "a.py",
        '"""Old module.\nMore text.\n"""\n\n'
        'async def f():\n    """Only statement."""\n\n'
        'class A: "Only statement."\n\n'
        'def g():\n    """Old guidance.\n    More text.\n    """\n    return 3\n\n'
        'if True: "obsolete"; x = 2\n',
    )
    repo.commit()
    prepare(
        capsys,
        "a.py:1:1 | DELETE | redundant | - | -",
        "a.py:6:5 | DELETE | redundant | - | -",
        "a.py:8:10 | DELETE | redundant | - | -",
        'a.py:11:5 | KEEP | external | docs | # KEEP: uses "quotes" and \\slashes',
        "a.py:16:10 | DELETE | redundant | - | -",
    )
    assert run() == 0, capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == (
        "\nasync def f():\n    ...\n\nclass A: ...\n\n"
        'def g():\n    """KEEP: uses \\"quotes\\" and \\\\slashes"""\n    return 3\n\n'
        "if True: x = 2\n"
    )
    assert main(["verify-strip"]) == 0


def test_strip_shell_uses_comment_nodes_and_preserves_crlf_and_bom(repo, capsys):
    path = repo.write("a.sh", "")
    path.write_bytes(
        b"\xef\xbb\xbf#!/bin/bash\r\n# obsolete\r\n"
        b'  printf "%s" "# literal"  # constraint  # obsolete\r\n'
        b"cat <<EOF\r\n# heredoc\r\nEOF\r\n"
    )
    repo.commit()
    prepare(
        capsys,
        "a.sh:2:1 | DELETE | redundant | - | -",
        "a.sh:3:28 | KEEP | external | docs | # KEEP: external constraint",
        "a.sh:3:42 | DELETE | redundant | - | -",
    )
    assert run() == 0, capsys.readouterr().err
    assert path.read_bytes() == (
        b"\xef\xbb\xbf#!/bin/bash\r\n  # KEEP: external constraint\r\n"
        b'  printf "%s" "# literal"\r\ncat <<EOF\r\n# heredoc\r\nEOF\r\n'
    )
    assert main(["verify-strip"]) == 0


@pytest.mark.parametrize("replacement", ["value = 1\n", "# changed\n"])
def test_strip_does_not_write_any_file_when_one_location_is_stale(repo, capsys, replacement):
    first = repo.write("first.py", "# original\n")
    last = repo.write("last.py", "# original\n")
    repo.commit()
    prepare(
        capsys,
        "first.py:1:1 | DELETE | redundant | - | -",
        "last.py:1:1 | ENCODE | constraint | evidence | -",
    )
    last.write_text(replacement, encoding="utf-8")
    assert run() == 2
    assert "last.py:1:1: does not match the saved audit output" in capsys.readouterr().err
    assert first.read_text(encoding="utf-8") == "# original\n"
    assert last.read_text(encoding="utf-8") == replacement


def test_strip_compares_exactly_the_displayed_prefix(repo, capsys):
    prefix = "# " + "界" * 58
    path = repo.write("a.py", prefix + " old tail\n")
    repo.commit()
    prepare(capsys, "a.py:1:1 | DELETE | redundant | - | -")
    path.write_text(prefix + " new tail\n", encoding="utf-8")
    assert run() == 0
    assert not path.read_bytes()
