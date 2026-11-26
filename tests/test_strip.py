import pytest

from no_comments.cli import main
from no_comments.strip import DOCSTRING_HINT

PY_BASE = (
    "import os\n"
    "\n"
    "\n"
    "def f(x):\n"
    '    """Return x plus one."""\n'
    "    # add one\n"
    "    y = x + 1  # note\n"
    "    # z = y * 2\n"
    "    return y\n"
)

SH_BASE = (
    "#!/usr/bin/env bash\n"
    "set -eu\n"
    "# greet the user\n"
    'name="world"  # default\n'
    "# echo debug\n"
    'echo "hello # $name"\n'
)


def run(capsys, *args):
    code = main(["verify-strip", *args])
    return code, capsys.readouterr().out


def strip_lines(text, *drop):
    return "".join(line for line in text.splitlines(True) if line.strip() not in drop)


def test_python_comments_removed_pass(repo, capsys):
    repo.write("a.py", PY_BASE)
    repo.commit()
    repo.write("a.py", strip_lines(PY_BASE, "# add one").replace("  # note", ""))
    assert run(capsys) == (0, "")


def test_python_docstring_removed_passes_with_note(repo, capsys):
    repo.write("a.py", PY_BASE)
    repo.write("b.py", 'def g():\n    """Only a docstring."""\n')
    repo.commit()
    repo.write("a.py", strip_lines(PY_BASE, '"""Return x plus one."""'))
    repo.write("b.py", "def g(): ...\n")
    code, out = run(capsys)
    assert code == 0
    assert out.splitlines() == [
        "a.py:5: docstring removed from f (HEAD)",
        "b.py:2: docstring removed from g (HEAD)",
        "",
        DOCSTRING_HINT,
    ]


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.replace("x + 1", "x + 2"),
        lambda s: s.replace("    # z = y * 2\n", "    z = y * 2\n"),
        lambda s: s.replace("    # add one\n    y = x + 1  # note\n", ""),
    ],
    ids=["literal", "uncommented-code", "code-after-comment-deleted"],
)
def test_python_code_change_fails(repo, capsys, edit):
    repo.write("a.py", PY_BASE)
    repo.commit()
    repo.write("a.py", edit(PY_BASE))
    assert run(capsys) == (1, "a.py: code changed\n")


def test_shell_comments_removed_pass(repo, capsys):
    repo.write("run.sh", SH_BASE)
    repo.commit()
    repo.write("run.sh", strip_lines(SH_BASE, "# greet the user").replace("  # default", ""))
    assert run(capsys) == (0, "")


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.replace('name="world"', 'name="there"'),
        lambda s: s.replace("# echo debug\n", "echo debug\n"),
        lambda s: s.replace("# greet the user\n" + 'name="world"  # default\n', ""),
        lambda s: s.replace('echo "hello # $name"', 'echo "hello"'),
    ],
    ids=["literal", "uncommented-code", "code-after-comment-deleted", "hash-in-string"],
)
def test_shell_code_change_fails(repo, capsys, edit):
    repo.write("run.sh", SH_BASE)
    repo.commit()
    repo.write("run.sh", edit(SH_BASE))
    assert run(capsys) == (1, "run.sh: code changed\n")


def test_syntax_error_exits_2(repo, capsys):
    repo.write("a.py", PY_BASE)
    repo.commit()
    repo.write("a.py", "def f(:\n")
    assert main(["verify-strip"]) == 2
    assert "a.py" in capsys.readouterr().err


def test_invalid_base_exits_2(repo, capsys):
    repo.write("a.py", PY_BASE)
    repo.commit()
    assert main(["verify-strip", "--base", "nope"]) == 2


def test_added_and_deleted_files_with_code_fail(repo, capsys):
    repo.write("a.py", PY_BASE)
    repo.commit()
    repo.git("rm", "-q", "a.py")
    repo.stage("b.sh", "echo hi\n")
    code, out = run(capsys)
    assert code == 1
    assert sorted(out.splitlines()) == ["a.py: code changed", "b.sh: code changed"]


def test_only_given_files_and_supported_files_are_checked(repo, capsys):
    repo.write("a.py", PY_BASE)
    repo.write("pkg/b.py", "x = 1  # note\n")
    repo.write("notes.md", "# title\n")
    repo.commit()
    repo.write("a.py", PY_BASE.replace("x + 1", "x + 2"))
    repo.write("pkg/b.py", "x = 1\n")
    repo.write("notes.md", "changed\n")
    assert run(capsys, "pkg/b.py") == (0, "")
    assert run(capsys) == (1, "a.py: code changed\n")


def test_base_ref_and_files_from_subdirectory(repo, capsys, monkeypatch):
    repo.write("pkg/b.py", "# one\nx = 1\n")
    base = repo.commit()
    repo.write("pkg/b.py", "# one\n# two\nx = 1\n")
    repo.commit()
    repo.write("pkg/b.py", "x = 1\n")
    monkeypatch.chdir(repo.root / "pkg")
    assert run(capsys, "--base", base, "b.py") == (0, "")
    repo.write("pkg/b.py", "x = 3\n")
    assert run(capsys, "--base", base, "b.py") == (1, "pkg/b.py: code changed\n")


@pytest.mark.parametrize(
    "name, before, after",
    [
        ("doc.ts", "/** Old docs */\nexport const x = 1; // old\n", "export const x = 1;\n"),
        ("env.d.ts", "declare const x: /* old */ string;\n", "declare const x: string;\n"),
        (
            "view.tsx",
            "const x = <p>\n  {/* gone */}\n  <b />\n</p>;\n",
            "const x = <p>\n  <b />\n</p>;\n",
        ),
        ("only.ts", "// old\n", ""),
        (
            "a.ts",
            'export * from "x" with { /* old */ kind: "custom" };\n',
            'export * from "x" with { kind: "custom" };\n',
        ),
    ],
)
def test_verify_strip_accepts_typescript_comment_only_changes(repo, capsys, name, before, after):
    repo.write(name, before)
    base = repo.commit()
    repo.write(name, after)
    assert run(capsys, "--base", base) == (0, "")


@pytest.mark.parametrize(
    "before, after",
    [
        ('const x = "// keep";', 'const x = "// change";'),
        ("const x = `/* keep */ ${1}`;", "const x = `/* change */ ${1}`;"),
        ("const x = <p> // text </p>;", "const x = <p> // other </p>;"),
        ("const x = <p> <b/> </p>;", "const x = <p><b/></p>;"),
        ("function f(){ return /*\n old */ 1; }", "function f(){ return 1; }"),
        ('export type * from "x";', 'export * from "x";'),
        ('import defer * as ns from "x";', 'import * as ns from "x";'),
        ('export * from "x" with { a: "old" };', 'export * from "x" with { a: "new" };'),
        ('export * from "x" with { a: "old" };', 'export * from "x";'),
    ],
)
def test_verify_strip_detects_typescript_code_changes(repo, capsys, before, after):
    repo.write("a.tsx", before)
    repo.commit()
    repo.write("a.tsx", after)
    assert run(capsys) == (1, "a.tsx: code changed\n")
