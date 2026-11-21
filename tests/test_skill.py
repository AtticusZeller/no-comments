import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from no_comments.cli import main

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
SKILL = SKILLS / "clean-comments"
EVIDENCE = SKILL / "scripts" / "evidence.sh"
SAMPLE = ROOT / "tests" / "fixtures" / "cleanup"
README = (ROOT / "README.md").read_text(encoding="utf-8")
SKILL_MD = (SKILL / "SKILL.md").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
VERSION = re.search(r'^version = "([^"]+)"$', PYPROJECT, re.M).group(1)
UVX = shutil.which("uvx")


def frontmatter(path: Path) -> dict:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, path
    return yaml.safe_load(match.group(1))


@pytest.mark.parametrize("skill", sorted(p.parent for p in SKILLS.glob("*/SKILL.md")))
def test_skill_frontmatter(skill):
    meta = frontmatter(skill / "SKILL.md")
    assert meta["name"] == skill.name
    assert isinstance(meta["description"], str) and meta["description"].strip()


def test_skill_references_exist():
    texts = [p.read_text(encoding="utf-8") for p in SKILL.rglob("*.md")]
    referenced = {m for text in texts for m in re.findall(r"(?:references|scripts)/[\w.-]+", text)}
    assert "references/reviewer.md" in referenced
    assert "scripts/evidence.sh" in referenced
    missing = sorted(r for r in referenced if not (SKILL / r).is_file())
    assert missing == []
    listed = {str(p.relative_to(SKILL)) for p in SKILL.rglob("*") if p.is_file()}
    assert listed - referenced == {"SKILL.md"}


def test_readme_install_command_matches_skill_dirs():
    names = re.findall(r"npx skills add AtticusZeller/no-comments --skill (\S+)", README)
    assert names
    assert set(names) == {p.parent.name for p in SKILLS.glob("*/SKILL.md")}


def test_skill_pins_cli_to_repository_version():
    pin = r"uvx --from git\+https://github\.com/AtticusZeller/no-comments@v(\S+) no-comments"
    pins = re.findall(pin, SKILL_MD)
    assert pins == [VERSION]
    assert "uv tool install" not in SKILL_MD


@pytest.mark.skipif(UVX is None and not os.environ.get("CI"), reason="needs uvx on PATH")
def test_uvx_runs_cli_from_repository():
    assert UVX is not None, "uvx must be on PATH in CI"
    result = subprocess.run(
        [UVX, "--no-cache", "--from", str(ROOT), "no-comments", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "verify-strip" in result.stdout


def test_evidence_script_without_gh(repo, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "git", "awk", "grep", "tr", "sort"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    repo.write("a.py", "x = 1\ny = 2\n")
    repo.commit("feat: add values")
    repo.write("a.py", "x = 10\ny = 2\n")
    repo.commit("fix: raise x for the vendor limit (#12)")
    repo.write("a.py", "x = 10\ny = 20\nz = 3\n")
    repo.commit("feat: add z")
    env = {**os.environ, "PATH": str(bin_dir)}
    result = subprocess.run(
        [str(bin_dir / "bash"), str(EVIDENCE), "a.py", "1", "2"],
        cwd=repo.root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    blame = out.split("== log", 1)[0]
    assert re.search(r"^[0-9a-f]{10} \d{4}-\d\d-\d\d 1 lines fix: raise x", blame, re.M)
    assert re.search(r"^[0-9a-f]{10} \d{4}-\d\d-\d\d 1 lines feat: add z", blame, re.M)
    log = out.split("== log", 1)[1].split("== PR", 1)[0]
    assert [line.split(" ", 2)[2] for line in log.strip().splitlines()[1:]] == [
        "feat: add z",
        "fix: raise x for the vendor limit (#12)",
        "feat: add values",
    ]
    assert out.split("== PR numbers in commit messages ==", 1)[1].split() == ["#12"]


def test_evidence_script_usage():
    result = subprocess.run(["bash", str(EVIDENCE)], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "usage" in result.stderr


def sample_files() -> list[str]:
    return sorted(
        str(p.relative_to(SAMPLE))
        for pattern in ("*.py", "*.sh")
        for p in SAMPLE.rglob(pattern)
        if "__pycache__" not in p.parts
    )


def test_expected_covers_every_sample_finding(monkeypatch, capsys):
    monkeypatch.chdir(SAMPLE)
    assert main(["audit", *sample_files()]) == 0
    found = {":".join(line.split(":")[:2]) for line in capsys.readouterr().out.splitlines()}
    expected = (SAMPLE / "expected.md").read_text(encoding="utf-8")
    row = r"^\| ([\w/.]+:\d+) \| (?:DELETE|ENCODE|KEEP|WORKAROUND) \|"
    rows = set(re.findall(row, expected, re.M))
    assert rows == found


def run_sample_tests(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_sample_tests_pass_and_lock_the_bom_workaround(tmp_path):
    copy = tmp_path / "sample"
    shutil.copytree(SAMPLE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    assert run_sample_tests(copy).returncode == 0
    io = copy / "ledger" / "io.py"
    lines = io.read_text(encoding="utf-8").splitlines(True)
    hack = [i for i, line in enumerate(lines) if "lstrip" in line]
    assert len(hack) == 1
    del lines[hack[0]]
    io.write_text("".join(lines), encoding="utf-8")
    result = run_sample_tests(copy)
    assert result.returncode == 1
    assert "test_load_bank_export" in result.stdout
