import re
from pathlib import Path

from no_comments.allow import COMMON_PREFIXES, PYTHON_PREFIXES, SHELL_PREFIXES
from no_comments.report import CODES

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
SCOPES = {"通用": COMMON_PREFIXES, "Python": PYTHON_PREFIXES, "Shell": SHELL_PREFIXES}


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
    version = re.search(r'^version = "([^"]+)"$', PYPROJECT, re.MULTILINE).group(1)
    found = re.findall(r"rev: v(\S+)", README) + re.findall(r"no-comments@v(\S+)", README)
    assert found
    assert set(found) == {version}


def test_rule_codes_match_report():
    assert set(re.findall(r"NC\d{3}", README)) == set(CODES.values())


def test_runtime_dependencies():
    block = re.search(r"^dependencies = \[(.*?)^\]", PYPROJECT, re.MULTILINE | re.DOTALL).group(1)
    names = {re.split(r"[<>=!~ \[]", d)[0] for d in re.findall(r'"([^"]+)"', block)}
    assert names == {"tree-sitter", "tree-sitter-bash"}


def test_claude_md_links_to_agents_md():
    claude = ROOT / "CLAUDE.md"
    assert claude.is_symlink()
    assert claude.readlink() == Path("AGENTS.md")


def test_readme_has_no_pending_section():
    assert not re.search(r"^#+\s*待定", README, re.MULTILINE)
