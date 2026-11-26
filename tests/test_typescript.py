import subprocess

import pytest

from no_comments.allow import is_allowed
from no_comments.cli import main
from no_comments.langs import Kind
from no_comments.langs.typescript import extract, extract_tsx


def test_tree_sitter_extracts_only_real_comments():
    source = (
        'const s = "// not a comment /* */";\n'
        'const t = `// text ${"/* string */"} ${1 /* interpolation */}`;\n'
        r"const pattern = /\/\/|\/\*/;"
        "\n"
        "const π = 3; // trailing\r\n"
        "/**\r\n * Documentation\r\n */\r\n"
        "const el = <p>// JSX text /* text */{/* JSX comment */}</p>;\n"
    )
    comments = extract_tsx(source)
    assert [(item.line, item.col, item.body) for item in comments] == [
        (2, 42, "interpolation"),
        (4, 14, "trailing"),
        (5, 1, "Documentation"),
        (8, 38, "JSX comment"),
    ]
    assert all(item.kind is Kind.COMMENT for item in comments)
    assert list(comments[2].lines) == [5, 6, 7]
    assert extract("const n = <number>value;") == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("// KEEP: reason", [True]),
        ("/** KEEP: reason */", [True]),
        ("// biome-ignore lint/suspicious/noExplicitAny: reason", [True]),
        ("/* biome-ignore lint: https://example.com */ /* extra */", [True, False]),
        ("// biome-ignore lint: https://example.com // extra", [True, False]),
        ("// biome-ignore lint: // extra", [False, False]),
        ("// biome-ignore lint: ", [False]),
        ("// biome-ignore whatever: reason", [False]),
        ("// biome-ignore lint", [False]),
        ('/// <reference types="vite/client" />', [True]),
        ("/// <reference lib='dom' preserve='true'/>", [True]),
        ('/// <reference path="./dir with spaces/env.d.ts"/> // extra', [True, False]),
        ('/// <reference path="./a//b.d.ts"/>', [True]),
        ('/// <reference types="pkg" resolution-mode="require" />', [True]),
        ('/// <reference no-default-lib="true"/>', [True]),
        ('/// <reference arbitrary="node"/>', [False]),
        ('/// <reference types="node" types="react"/>', [False]),
        ('/// <reference types="node" /> narrative', [False]),
        ('// <reference types="node" />', [False]),
        ('//// <reference types="node" />', [False]),
        ('const x = 1;\n/// <reference types="node" />', [False]),
        ("// shellcheck disable=SC2086", [False]),
    ],
)
def test_directive_allowance(text, expected):
    assert [is_allowed("typescript", item) for item in extract(text)] == expected


def test_check_and_audit_report_all_typescript_comment_kinds(repo, capsys):
    repo.stage(
        "env.d.ts",
        '/// <reference types="vite/client" />\ndeclare const env: string;\n',
    )
    repo.stage("a.ts", "// line\n/** JSDoc */\nexport const a = 1; /* first\nsecond */\n")
    repo.stage("view.tsx", "export const view = <p>{/* JSX */}</p>;\n")
    repo.stage("plain.js", "// not checked\n")
    expected = [
        "a.ts:1:1: NC001 comment not allowed: // line",
        "a.ts:2:1: NC001 comment not allowed: /** JSDoc */",
        r"a.ts:3:21: NC001 comment not allowed: /* first\nsecond */",
        "view.tsx:1:25: NC001 comment not allowed: /* JSX */",
    ]
    paths = ["env.d.ts", "a.ts", "view.tsx", "plain.js"]
    assert main(["check", *paths]) == 1
    assert capsys.readouterr().out.splitlines()[:5] == [*expected, ""]
    assert main(["audit", *paths]) == 0
    assert capsys.readouterr().out.splitlines() == expected


def test_check_reports_change_inside_multiline_comment(repo, capsys):
    repo.write("a.ts", "/* first\nsecond\n*/\n")
    repo.commit()
    repo.stage("a.ts", "/* first\nreplacement\n*/\n")
    assert main(["check", "a.ts"]) == 1
    assert "a.ts:1:1: NC001" in capsys.readouterr().out


def test_changing_code_before_same_comment_passes(repo):
    repo.write("a.ts", "const x = 1; // existing\n")
    repo.commit()
    repo.stage("a.ts", "const x = 2; // existing\n")
    assert main(["check", "a.ts"]) == 0


def test_moving_indented_jsdoc_from_ts_to_tsx_passes(repo):
    repo.write("from.ts", "/**\n * Existing docs\n */\nexport const a = 1;\n")
    repo.write("to.tsx", "export const view = <p />;\n")
    repo.commit()
    repo.stage("from.ts", "export const a = 1;\n")
    repo.stage(
        "to.tsx",
        "export const view = (\n  /**\n   * Existing docs\n   */\n  <p />\n);\n",
    )
    assert main(["check", "to.tsx"]) == 0


def test_rename_reports_only_new_comment(repo, capsys):
    old = "export const longName = 'unchanged on rename'; // existing\n"
    repo.write("old.ts", old)
    repo.commit()
    repo.git("mv", "old.ts", "new.ts")
    repo.stage("new.ts", old + "// added\n")
    assert main(["check", "new.ts"]) == 1
    out = capsys.readouterr().out
    assert "new.ts:2:1: NC001" in out
    assert "existing" not in out


def test_merge_resolution_reports_new_comment_but_not_incoming_comment(repo, capsys):
    repo.write("a.ts", "const a = 1;\n")
    base = repo.commit()
    repo.git("checkout", "-b", "feature", base)
    repo.write("a.ts", "const a = 2; // incoming\n")
    repo.commit()
    repo.git("checkout", "main")
    repo.write("a.ts", "const a = 3;\n")
    repo.commit()
    result = subprocess.run(["git", "merge", "feature"], capture_output=True, check=False)
    assert result.returncode == 1
    repo.stage("a.ts", "const a = 4; // incoming\n// from resolution\n")
    assert main(["check", "a.ts"]) == 1
    out = capsys.readouterr().out
    assert "a.ts:2:1: NC001" in out
    assert "incoming" not in out


def test_syntax_errors_warn_and_skip_file(repo, capsys):
    repo.stage("broken.ts", "const x = ; // ordinary\n")
    assert main(["check", "broken.ts"]) == 0
    output = capsys.readouterr()
    assert "warning: skipping broken.ts" in output.err
    assert not output.out


def test_strip_leaves_typescript_unsupported(repo, capsys):
    source = "const n = 1; // note\n"
    file = repo.write("a.ts", source)
    repo.commit()
    assert main(["audit", "a.ts"]) == 0
    repo.write("audit.txt", capsys.readouterr().out)
    repo.write("review.txt", "a.ts:1:14 | DELETE | redundant | - | -\n")
    assert main(["strip", "review.txt", "--audit", "audit.txt"]) == 2
    assert "not a supported source file" in capsys.readouterr().err
    assert file.read_text() == source
    repo.write("a.ts", "const n = 2;\n")
    assert main(["verify-strip"]) == 0
    assert main(["verify-strip", "a.ts"]) == 0
