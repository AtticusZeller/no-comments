import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from no_comments.allow import COMMON_PREFIXES, PYTHON_PREFIXES, SHELL_PREFIXES
from no_comments.langs.typescript import BIOME_PREFIX, REFERENCE_PREFIX
from no_comments.report import CODES

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
SCOPES = {
    "通用": COMMON_PREFIXES,
    "Python": PYTHON_PREFIXES,
    "Shell": SHELL_PREFIXES,
    "TypeScript、TSX": (BIOME_PREFIX, REFERENCE_PREFIX),
}


def allow_table() -> dict[str, list[str]]:
    lines = README.splitlines()
    start = lines.index("| 范围 | 前缀 |") + 2
    table: dict[str, list[str]] = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        scope, prefix = (cell.strip() for cell in line.strip("|").split("|"))
        table.setdefault(scope, []).append(prefix.strip("`"))
    return table


def test_allow_table_matches_allow_py():
    expected = {scope: sorted(prefixes) for scope, prefixes in SCOPES.items()}
    assert {scope: sorted(p) for scope, p in allow_table().items()} == expected


def test_readme_versions_match_pyproject():
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT, re.MULTILINE)
    assert match is not None
    version = match[1]
    found = re.findall(r"rev: v(\S+)", README) + re.findall(r"no-comments@v(\S+)", README)
    assert found
    assert set(found) == {version}


def test_rule_codes_match_report():
    assert set(re.findall(r"NC\d{3}", README)) == set(CODES.values())


def test_runtime_dependencies():
    match = re.search(r"^dependencies = \[(.*?)^\]", PYPROJECT, re.MULTILINE | re.DOTALL)
    assert match is not None
    block = match[1]
    names = {re.split(r"[<>=!~ \[]", d)[0] for d in re.findall(r'"([^"]+)"', block)}
    assert names == {"tree-sitter", "tree-sitter-bash", "tree-sitter-typescript"}


def test_claude_md_links_to_agents_md():
    claude = ROOT / "CLAUDE.md"
    assert claude.is_symlink()
    assert claude.readlink() == Path("AGENTS.md")


def test_readme_has_no_pending_section():
    assert not re.search(r"^#+\s*待定", README, re.MULTILINE)


def test_frontend_templates_call_check_with_staged_filenames(repo):
    repo.stage("-dash.d.ts", "// forbidden\n")
    repo.stage("src/space name.tsx", "const view = <p>{/* forbidden */}</p>;\n")
    repo.stage("src/generated/client.ts", "// generated\n")
    repo.stage("plain.js", "// ignored\n")
    repo.write("unstaged.ts", "// not staged\n")
    uvx = repo.write(
        "bin/uvx",
        '#!/bin/sh\n[ "$1" = --from ] && [ "$3" = no-comments ] || exit 2\n'
        f'shift 3\nexec {shlex.quote(str(Path(sys.executable).parent / "no-comments"))} "$@"\n',
    )
    uvx.chmod(0o755)
    env = {**os.environ, "PATH": f"{uvx.parent}{os.pathsep}{os.environ['PATH']}"}
    lefthook = yaml.safe_load(README.split("```yaml\n# lefthook.yml\n")[1].split("```")[0])
    run = lefthook["pre-commit"]["jobs"][0]["run"]
    command = run.replace("{staged_files}", shlex.join(["-dash.d.ts", "src/space name.tsx"]))
    husky = README.split("```sh\n# .husky/pre-commit\n")[1].split("```")[0]
    for hook in (command, husky):
        result = subprocess.run(
            ["sh", "-c", hook], env=env, capture_output=True, text=True, check=False
        )
        violations = [line for line in result.stdout.splitlines() if " NC001 " in line]
        assert result.returncode != 0, result.stdout + result.stderr
        assert result.stderr == ""
        assert violations == [
            "-dash.d.ts:1:1: NC001 comment not allowed: // forbidden",
            "src/space name.tsx:1:18: NC001 comment not allowed: /* forbidden */",
        ]
