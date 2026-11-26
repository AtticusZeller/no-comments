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
        ("// biome-ignore format: preserve this layout", [True]),
        ("// biome-ignore format/group: invalid", [False]),
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


@pytest.mark.parametrize("command", ["check", "audit"])
def test_typescript_parse_error_does_not_pass(repo, capsys, command):
    repo.stage("broken.ts", "const x = ; // ordinary\n")
    assert main([command, "broken.ts"]) == 2
    assert "broken.ts: could not parse TypeScript or TSX" in capsys.readouterr().err


@pytest.mark.parametrize(
    "statement",
    [
        'export type * from "./dep";',
        'export type /* modifier note */ * as ns from "./dep";',
        'import defer * as mod from "./dep";',
        'import data from "./data.json" with { type: "json" };',
        'export { default } from "./data.json" with { type: "json" };',
    ],
)
def test_modern_typescript_syntax_is_checked_and_audited(repo, capsys, statement):
    repo.stage("modern.ts", f'{statement} // real\nconst x = "// not a comment";\n')
    expected = f"modern.ts:1:{len(statement) + 2}: NC001 comment not allowed: // real"
    assert main(["check", "modern.ts"]) == 1
    captured = capsys.readouterr()
    findings = [line for line in captured.out.splitlines() if "NC001" in line]
    assert findings[-1:] == [expected]
    assert len(findings) == 1 + ("/* modifier note */" in statement)
    assert not captured.err
    assert main(["audit", "modern.ts"]) == 0
    assert capsys.readouterr().out.splitlines() == findings


@pytest.mark.parametrize("existing", ["a.ts", "src/generated/a.ts"])
def test_retained_comment_does_not_take_duplicate_slot(repo, capsys, existing):
    repo.write(existing, "export const a = 1; // same\n")
    repo.commit()
    repo.stage(existing, "export const a = 2; // same\n")
    repo.stage("z.ts", "export const z = 3; // same\n")
    for targets in ([existing, "z.ts"], ["z.ts"]):
        assert main(["check", *targets]) == 1
        out = capsys.readouterr().out
        assert [line for line in out.splitlines() if "NC001" in line] == [
            "z.ts:1:21: NC001 comment not allowed: // same"
        ]


def test_biome_multi_rule_suppression_only_reports_ordinary_tail(repo, capsys):
    directive = "// biome-ignore lint/suspicious/noExplicitAny lint/suspicious/noConsole: reason"
    code = "console.log(1 as any);\n"
    repo.stage("a.ts", f"{directive}\n{code}")
    assert main(["check", "a.ts"]) == 0
    repo.stage("a.ts", f"{directive} // ordinary\n{code}")
    assert main(["check", "a.ts"]) == 1
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if "NC001" in line] == [
        f"a.ts:1:{len(directive) + 2}: NC001 comment not allowed: // ordinary"
    ]


def test_biome_protocol_relative_url_is_not_a_comment_suffix(repo, capsys):
    directive = "// biome-ignore format: Refer to //example.test/docs"
    repo.stage("a.ts", f"{directive} // ordinary\nexport const x = [1,2];\n")
    assert main(["check", "a.ts"]) == 1
    assert capsys.readouterr().out.splitlines()[0] == (
        f"a.ts:1:{len(directive) + 2}: NC001 comment not allowed: // ordinary"
    )


def test_retained_multiline_comment_matches_replaced_continuation(repo, capsys):
    repo.write("a.ts", "/* existing\n   comment */\n")
    repo.commit()
    repo.stage("a.ts", "/* existing\n  comment */\n")
    repo.stage("z.ts", "/* existing\n   comment */\n")
    assert main(["check", "a.ts", "z.ts"]) == 1
    assert capsys.readouterr().out.splitlines()[0].startswith("z.ts:1:1: NC001")


@pytest.mark.parametrize(
    "name, source, row",
    [
        ("star.ts", 'export * from "./dep" with { custom: "value" };', 1),
        ("namespace.ts", 'export * as ns from "./dep" with { custom: "value" };', 1),
        ("named.ts", 'export { thing } from "./dep" with { custom: "value" };', 1),
        (
            "nested.d.ts",
            'declare module "fixture" {\n  export type * from "type-dependency";\n}',
            2,
        ),
    ],
)
@pytest.mark.parametrize("has_comment", [False, True], ids=["clean", "commented"])
def test_module_syntax_variants_are_checked_and_audited(
    repo, capsys, name, source, row, has_comment
):
    lines = source.splitlines()
    col = len(lines[row - 1]) + 2
    if has_comment:
        lines[row - 1] += " // real"
    repo.stage(name, "\n".join(lines) + "\n")
    expected = [f"{name}:{row}:{col}: NC001 comment not allowed: // real"] if has_comment else []
    assert main(["check", name]) == int(has_comment)
    output = capsys.readouterr()
    assert [line for line in output.out.splitlines() if "NC001" in line] == expected
    assert not output.err
    assert main(["audit", name]) == 0
    assert capsys.readouterr().out.splitlines() == expected


def test_attribute_recovery_preserves_comments_but_not_markers_inside_strings():
    source = (
        'export * from "./dep" /* before */ with {\n'
        '  "/* key */": "// value }", /* inside */\n'
        "}; // after\n"
        'const text = `export * from "./other" with { fake: "// text" }`;\n'
    )
    assert [c.text for c in extract(source)] == ["/* before */", "/* inside */", "// after"]


@pytest.mark.parametrize("command", ["check", "audit"])
@pytest.mark.parametrize(
    "source",
    [
        'export * from "./dep" with { custom: };',
        'export * from "./dep" with { custom: 1 };',
        'const value = "./dep" with { custom: "value" };',
    ],
)
def test_malformed_module_attributes_do_not_pass(repo, capsys, command, source):
    repo.stage("broken.ts", f"{source} // ordinary\n")
    assert main([command, "broken.ts"]) == 2
    assert "broken.ts: could not parse TypeScript or TSX" in capsys.readouterr().err


@pytest.mark.parametrize(
    "before, after",
    [
        ("export const a = 1; // same\n", "export const intro = 0;\nexport const a = 2; // same\n"),
        ("export const intro = 0;\nexport const a = 1; // same\n", "export const a = 2; // same\n"),
    ],
    ids=["insert", "delete"],
)
def test_shifted_retained_comment_does_not_take_duplicate_slot(repo, capsys, before, after):
    generated = "src/generated/a.ts"
    repo.write(generated, before)
    repo.commit()
    repo.stage(generated, after)
    repo.stage("z.ts", "export const z = 3; // same\n")
    for targets in ([generated, "z.ts"], ["z.ts"]):
        assert main(["check", *targets]) == 1
        out = capsys.readouterr().out
        assert [line for line in out.splitlines() if "NC001" in line] == [
            "z.ts:1:21: NC001 comment not allowed: // same"
        ]


@pytest.fixture(
    params=[
        ("@jsx", "/** @jsx alternate */", "/** @jsx h */"),
        ("@jsxFrag", "/** @jsxFrag Alternate */", "/** @jsxFrag Fragment */"),
        ("@jsxImportSource", "/** @jsxImportSource preact */", "/** @jsxImportSource react */"),
        ("@jsxRuntime", "/** @jsxRuntime classic */", "/** @jsxRuntime automatic */"),
        ("@ts-expect-error", "// @ts-expect-error original", "// @ts-expect-error revised"),
        ("@ts-ignore", "// @ts-ignore original", "// @ts-ignore revised"),
        ("@ts-nocheck", "// @ts-nocheck original", "// @ts-nocheck revised"),
        ("@ts-check", "// @ts-check original", "// @ts-check revised"),
        (
            "/// <reference>",
            '/// <reference path="./a.d.ts" />',
            '/// <reference path="./b.d.ts" />',
        ),
        ("/// <amd-module>", '/// <amd-module name="a" />', '/// <amd-module name="b" />'),
        (
            "/// <amd-dependency>",
            '/// <amd-dependency path="a" />',
            '/// <amd-dependency path="b" />',
        ),
    ],
    ids=[
        "jsx",
        "jsxFrag",
        "jsxImportSource",
        "jsxRuntime",
        "expect",
        "ignore",
        "nocheck",
        "check",
        "reference",
        "amd-module",
        "amd-dependency",
    ],
)
def compiler_directive(request):
    return request.param


@pytest.mark.parametrize("action", ["DELETE", "KEEP"])
def test_strip_refuses_to_rewrite_compiler_directives_atomically(
    repo, capsys, compiler_directive, action
):
    name, comment, _ = compiler_directive
    first = repo.write("a.ts", "// stale\nconst a = 1;\n")
    sample = repo.write("sample.tsx", f"{comment}\nconst x = <div />;\n")
    repo.commit()
    assert main(["audit"]) == 0
    audit = capsys.readouterr().out
    assert ("sample.tsx:1:1: NC001" in audit) == (name != "/// <reference>")
    repo.write("audit.txt", audit)
    repo.write(
        "review.txt",
        f"a.ts:1:1 | DELETE | stale | - | -\nsample.tsx:1:1 | {action} | rationale | docs | // KEEP: external\n",
    )
    assert main(["strip", "review.txt", "--audit", "audit.txt"]) == 2
    output = capsys.readouterr().err
    assert f"compiler directive {name}" in output
    assert "WORKAROUND or ENCODE" in output
    assert first.read_text() == "// stale\nconst a = 1;\n"
    assert sample.read_text() == f"{comment}\nconst x = <div />;\n"


@pytest.mark.parametrize("change", ["add", "delete", "keep", "modify"])
def test_verify_strip_reports_changed_compiler_directive(repo, capsys, compiler_directive, change):
    name, comment, modified = compiler_directive
    jsx = "const x = <div />;\n"
    before, after = {
        "add": ("", comment),
        "delete": (comment, ""),
        "keep": (comment, "// KEEP: outside"),
        "modify": (comment, modified),
    }[change]
    repo.write("sample.tsx", before + "\n" + jsx)
    repo.commit()
    repo.write("sample.tsx", after + "\n" + jsx)
    assert main(["verify-strip"]) == 1
    assert (
        f"sample.tsx: code changed (compiler directive changed: {name})" in capsys.readouterr().out
    )


def test_verify_strip_detects_suppression_moved_to_another_statement(repo, capsys):
    repo.write("a.ts", "// @ts-ignore\nconst x = 1;\nconst y = 2;\n")
    repo.commit()
    repo.write("a.ts", "const x = 1;\n// @ts-ignore\nconst y = 2;\n")
    assert main(["verify-strip"]) == 1
    assert "compiler directive changed: @ts-ignore" in capsys.readouterr().out


def test_verify_strip_detects_reordered_file_type_check_switches(repo, capsys):
    repo.write("a.ts", "// @ts-check\n// @ts-nocheck\nconst x = 1;\n")
    repo.commit()
    repo.write("a.ts", "// @ts-nocheck\n// @ts-check\nconst x = 1;\n")
    assert main(["verify-strip"]) == 1
    assert "compiler directive changed: @ts-check, @ts-nocheck" in capsys.readouterr().out


def test_verify_strip_accepts_ordinary_comment_and_inactive_header_lookalikes(repo, capsys):
    literals = 'const text = "// @ts-nocheck";\nconst hint = `/** @jsx other */`;\n'
    repo.write("a.ts", literals + "// @ts-nocheck\n/** @jsx other */\nconst x = 1;\n")
    repo.commit()
    repo.write("a.ts", literals + "const x = 1;\n")
    assert main(["verify-strip"]) == 0
    assert not capsys.readouterr().out


def test_verify_strip_preserves_block_and_triple_slash_suppressions(repo, capsys):
    repo.write("a.ts", "const x = 1;\n/* @ts-ignore */\n/// @ts-expect-error\nconst y = 2;\n")
    repo.commit()
    repo.write("a.ts", "const x = 1;\nconst y = 2;\n")
    assert main(["verify-strip"]) == 1
    assert "compiler directive changed: @ts-ignore, @ts-expect-error" in capsys.readouterr().out
