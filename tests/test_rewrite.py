import os
import subprocess
import sys
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


def execute(*command):
    result = subprocess.run(command, check=True, capture_output=True)
    assert not result.stderr
    return result.stdout


@pytest.mark.parametrize("space", [b" ", b"\t"], ids=["space", "tab"])
def test_shell_strip_and_verify_preserve_escaped_whitespace(repo, capsys, space):
    path = repo.write("a.sh", "")
    prefix = b'printf "<%s>\\n" foo\\'
    next_line = b'\nprintf "next\\n"\n'
    source = prefix + space + b"  # stale" + next_line
    path.write_bytes(source)
    repo.commit()
    before = execute("bash", "a.sh")
    assert before == b"<foo" + space + b">\nnext\n"
    col = source.index(b"#") + 1
    prepare(capsys, f"a.sh:1:{col} | DELETE | redundant | - | -")
    assert run() == 0
    assert path.read_bytes() == prefix + space + next_line
    assert execute("bash", "a.sh") == before
    assert main(["verify-strip"]) == 0
    path.write_bytes(prefix + next_line)
    assert execute("bash", "a.sh") != before
    assert main(["verify-strip"]) == 1
    assert "a.sh: code changed" in capsys.readouterr().out


def test_strip_keeps_newline_that_ends_a_shell_continuation(repo, capsys):
    path = repo.write("a.sh", "")
    prefix = b'printf "%s\\n" first \\\n'
    next_command = b'printf "next\\n"\n'
    path.write_bytes(prefix + b"# stale\n" + next_command)
    repo.commit()
    before = execute("bash", "a.sh")
    prepare(capsys, "a.sh:2:1 | DELETE | redundant | - | -")
    assert run() == 0
    assert path.read_bytes() == prefix + b"\n" + next_command
    assert execute("bash", "a.sh") == before == b"first\nnext\n"
    assert main(["verify-strip"]) == 0
    path.write_bytes(prefix + next_command)
    assert execute("bash", "a.sh") != before
    assert main(["verify-strip"]) == 1


@pytest.mark.parametrize(
    ("source", "rows", "unsafe"),
    [
        (
            '# stale\n# stale again\n# coding: latin-1\nprint("é")\n',
            ("1:1 | DELETE | redundant | - | -", "2:1 | DELETE | redundant | - | -"),
            '# coding: latin-1\nprint("é")\n',
        ),
        (
            'print("é") # stale\n',
            ("1:12 | KEEP | external | docs | # KEEP: reference coding: latin-1",),
            '# KEEP: reference coding: latin-1\nprint("é")\n',
        ),
        (
            '# stale\n# reminder\n# coding: utf-8\nprint("é")\n',
            ("1:1 | DELETE | redundant | - | -",),
            '# reminder\n# coding: utf-8\nprint("é")\n',
        ),
    ],
    ids=["moved-cookie", "inserted-cookie", "same-codec-new-cookie"],
)
def test_strip_rejects_effective_python_encoding_changes(repo, capsys, source, rows, unsafe):
    earlier = repo.write("first.py", "# stale\nprint(1)\n")
    path = repo.write("a.py", source)
    repo.commit()
    before = execute(sys.executable, "a.py")
    prepare(capsys, "first.py:1:1 | DELETE | redundant | - | -", *(f"a.py:{r}" for r in rows))
    assert run() == 2
    assert "effective Python encoding declaration changed" in capsys.readouterr().err
    assert earlier.read_bytes() == b"# stale\nprint(1)\n"
    assert path.read_bytes() == source.encode()
    assert execute(sys.executable, "a.py") == before == "é\n".encode()
    path.write_bytes(unsafe.encode())
    assert main(["verify-strip"]) == 1
    assert "a.py: code changed" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["a.sh", "a.py"])
def test_strip_rejects_activated_or_lost_shebang(repo, capsys, name):
    code = b'printf "ok\\n"\n' if name.endswith(".sh") else b'print("ok")\n'
    path = repo.write(name, "")
    source = b"# stale\n#!/bin/false\n" + code
    path.write_bytes(source)
    path.chmod(0o755)
    repo.commit()
    before = (
        execute("bash", "-c", "./a.sh") if name.endswith(".sh") else execute(sys.executable, name)
    )
    prepare(capsys, f"{name}:1:1 | DELETE | redundant | - | -")
    assert run() == 2
    assert "effective shebang changed" in capsys.readouterr().err
    assert path.read_bytes() == source
    after = (
        execute("bash", "-c", "./a.sh") if name.endswith(".sh") else execute(sys.executable, name)
    )
    assert after == before == b"ok\n"
    path.write_bytes(source.partition(b"\n")[2])
    assert main(["verify-strip"]) == 1
    if name.endswith(".sh"):
        failed = subprocess.run(["./a.sh"], check=False, capture_output=True)
        assert (failed.returncode, failed.stdout) == (1, b"")
    repo.commit()
    path.write_bytes(source)
    assert main(["verify-strip"]) == 1


def test_strip_preserves_python_shebang_encoding_crlf_and_tabs(repo, capsys):
    path = repo.write("a.py", "")
    header = b"#!/usr/bin/env python3\r\n# coding: utf-8\r\ndef f():\r\n"
    body = '\tx = "é"  # stale\r\n\treturn x\r\nprint(f())\r\n'.encode()
    path.write_bytes(header + body)
    repo.commit()
    before = execute(sys.executable, "a.py")
    prepare(capsys, "a.py:4:11 | KEEP | external | docs | # KEEP: external constraint")
    assert run() == 0, capsys.readouterr().err
    assert path.read_bytes() == header + b"\t# KEEP: external constraint\r\n" + body.replace(
        b"  # stale", b""
    )
    assert execute(sys.executable, "a.py") == before
    assert main(["verify-strip"]) == 0


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires privileges on Windows")
@pytest.mark.parametrize("link_type", ["file", "parent"])
def test_audit_skips_symlinks_and_strip_rejects_them(repo, tmp_path, capsys, link_type):
    original = b"# stale\nvalue = 1\n"
    target = tmp_path / "external.py"
    target.write_bytes(original)
    first = repo.write("first.py", "# stale\n")
    if link_type == "file":
        name = "link.py"
        Path(name).symlink_to(target)
    else:
        name = "link/external.py"
        Path("link").symlink_to(tmp_path, target_is_directory=True)
    repo.commit()
    prepare(
        capsys,
        "first.py:1:1 | DELETE | redundant | - | -",
        f"{name}:1:1 | DELETE | redundant | - | -",
    )
    saved = Path("audit.txt").read_text()
    assert saved == "first.py:1:1: NC001 comment not allowed: # stale\n"
    assert main(["audit", name]) == 0
    assert not capsys.readouterr().out
    Path("audit.txt").write_text(saved + f"{name}:1:1: NC001 comment not allowed: # stale\n")
    assert run() == 2
    assert f"{name}:1:1: symbolic links are not supported" in capsys.readouterr().err
    assert first.read_bytes() == b"# stale\n"
    assert target.read_bytes() == original
    assert repo.git("diff", "--name-only") == ""


@pytest.mark.parametrize(
    ("decision", "suggestion", "preserved"),
    [
        ("DELETE", "-", b""),
        ("KEEP", "# KEEP: external constraint", b"    # KEEP: external constraint\n"),
        ("ENCODE", "-", b"    # constraint\n"),
    ],
)
def test_strip_combines_docstring_and_nested_comment_edits(
    repo, capsys, decision, suggestion, preserved
):
    path = repo.write("a.py", "")
    header = b"def f():\n"
    code = b"    return 1\nprint(f())\n"
    path.write_bytes(header + b'    (\n        "old"  # constraint\n    )\n' + code)
    repo.commit()
    before = execute(sys.executable, "a.py")
    prepare(
        capsys,
        "a.py:2:5 | DELETE | redundant | - | -",
        f"a.py:3:16 | {decision} | external | docs | {suggestion}",
    )
    assert run() == 0, capsys.readouterr().err
    assert path.read_bytes() == header + preserved + code
    assert execute(sys.executable, "a.py") == before
    assert main(["verify-strip"]) == 0


@pytest.mark.parametrize(
    ("name", "command", "source", "location", "rewritten"),
    [
        (
            "a.py",
            sys.executable,
            b'def f():\n    x = """literal\n# inside string\n"""  # stale\n    return x\nprint(f())\n',
            "4:6",
            b'def f():\n    # KEEP: external constraint\n    x = """literal\n# inside string\n"""\n    return x\nprint(f())\n',
        ),
        (
            "a.sh",
            "bash",
            b'printf "%s\\n" "one\ntwo"  # stale\n',
            "2:7",
            b'# KEEP: external constraint\nprintf "%s\\n" "one\ntwo"\n',
        ),
        (
            "a.sh",
            "bash",
            b"cat \\\n <<EOF # stale\nbody\nEOF\n",
            "2:8",
            b"# KEEP: external constraint\ncat \\\n <<EOF\nbody\nEOF\n",
        ),
    ],
    ids=["python-string", "shell-string", "shell-heredoc"],
)
def test_strip_places_keep_above_multiline_statement(
    repo, capsys, name, command, source, location, rewritten
):
    path = repo.write(name, "")
    path.write_bytes(source)
    repo.commit()
    before = execute(command, name)
    prepare(capsys, f"{name}:{location} | KEEP | external | docs | # KEEP: external constraint")
    assert run() == 0, capsys.readouterr().err
    assert path.read_bytes() == rewritten
    assert execute(command, name) == before
    assert main(["verify-strip"]) == 0


def test_strip_reports_paths_written_before_io_failure(repo, capsys, monkeypatch):
    first = repo.write("first.py", "# stale\nx = 1\n")
    last = repo.write("last.py", "# stale\nx = 2\n")
    repo.commit()
    prepare(
        capsys,
        "first.py:1:1 | DELETE | redundant | - | -",
        "last.py:1:1 | DELETE | redundant | - | -",
    )
    original_write = Path.write_bytes

    def write(path, data):
        if path == last:
            raise PermissionError("permission denied")
        return original_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", write)
    assert run() == 2
    assert (
        f"could not write {last}: permission denied; already written: {first}"
        in capsys.readouterr().err
    )
    assert first.read_bytes() == b"x = 1\n"
    assert last.read_bytes() == b"# stale\nx = 2\n"


def test_strip_rejects_keep_suggestion_with_multiple_comment_segments(repo, capsys):
    path = repo.write("a.py", "x = 1  # stale\n")
    repo.commit()
    prepare(capsys, "a.py:1:8 | KEEP | external | docs | # KEEP: literal # x")
    assert run() == 2
    assert "a.py:1:8: KEEP suggestion must be a single comment segment" in capsys.readouterr().err
    assert path.read_bytes() == b"x = 1  # stale\n"
