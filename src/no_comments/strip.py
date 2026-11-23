import ast
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from no_comments.detect import EXTENSIONS, shebang_language
from no_comments.diff import _git_bytes, git
from no_comments.langs import ParseError, python, shell

DOCSTRING_HINT = (
    "删掉的 docstring 可能被 typer、click、FastAPI 等框架当作帮助文本或接口描述读取（`__doc__`），"
    "确认这些位置不依赖它，或改成显式传入 help=、description=。"
)


@dataclass
class StripReport:
    changed: list[str] = field(default_factory=list)
    removed_docstrings: list[tuple[str, int, str]] = field(default_factory=list)


def _is_noop(node: ast.stmt) -> bool:
    if isinstance(node, ast.Pass):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and (isinstance(node.value.value, str) or node.value.value is Ellipsis)
    )


def python_code(source: str) -> str:
    tree = python.parse_tree(source)
    for node in list(ast.walk(tree)):
        for name, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(v, ast.stmt) for v in value):
                setattr(node, name, [stmt for stmt in value if not _is_noop(stmt)])
    return ast.dump(tree)


def docstring_owners(source: str) -> dict[str, int]:
    tree = python.parse_tree(source)
    found: dict[str, int] = {}
    if ast.get_docstring(tree, clean=False) is not None:
        found["<module>"] = tree.body[0].lineno

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if ast.get_docstring(child, clean=False) is not None:
                    found[name] = child.body[0].lineno
                visit(child, name + ".")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def shell_code(source: str) -> list[str]:
    lines = source.split("\n")
    for comment in sorted(shell.extract(source), key=lambda c: (c.line, c.col), reverse=True):
        row = lines[comment.line - 1]
        start = comment.col - 1
        lines[comment.line - 1] = row[:start] + row[start + len(comment.text) :]
    return [line.rstrip() for line in lines if line.strip()]


def _shebang_language(source: str) -> str | None:
    return shebang_language(source.split("\n", 1)[0].encode("utf-8"))


def _decode(data: bytes | None, label: str) -> str:
    if data is None:
        return ""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(f"{label}: not UTF-8") from exc


def _base_blob(base: str, path: str) -> bytes | None:
    listed = _git_bytes("ls-tree", "-z", "--full-tree", base, "--", path)
    if not listed:
        return None
    if b" blob " not in listed.split(b"\t", 1)[0]:
        return None
    return _git_bytes("cat-file", "blob", f"{base}:{path}")


def _language(path: str, base_source: str, work_source: str) -> str | None:
    suffix = Path(path).suffix
    if suffix in EXTENSIONS:
        return EXTENSIONS[suffix]
    return _shebang_language(work_source) or _shebang_language(base_source)


def verify(base: str, files: Sequence[str]) -> StripReport:
    git("rev-parse", "--verify", f"{base}^{{commit}}")
    root = Path(git("rev-parse", "--show-toplevel").strip()).resolve()
    if files:
        paths = [
            os.path.relpath(Path(name).absolute().parent.resolve() / Path(name).name, root)
            for name in files
        ]
    else:
        listed = _git_bytes(
            "-c",
            "core.quotepath=off",
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--no-relative",
            "--no-ext-diff",
            "--no-textconv",
            base,
        )
        paths = [p for p in listed.decode("utf-8", "replace").split("\0") if p]
    report = StripReport()
    for path in paths:
        disk = root / path
        work_bytes = disk.read_bytes() if disk.is_file() else None
        base_bytes = _base_blob(base, path)
        base_source = _decode(base_bytes, f"{path} ({base})")
        work_source = _decode(work_bytes, path)
        lang = _language(path, base_source, work_source)
        if lang is None or base_source == work_source:
            continue
        try:
            if lang == "python":
                same = python_code(base_source) == python_code(work_source)
                if same:
                    kept = docstring_owners(work_source)
                    report.removed_docstrings += [
                        (path, line, name)
                        for name, line in docstring_owners(base_source).items()
                        if name not in kept
                    ]
            else:
                same = shell_code(base_source) == shell_code(work_source)
        except ParseError as exc:
            raise ParseError(f"{path}: {exc}") from exc
        if not same:
            report.changed.append(path)
    return report


def run_verify_strip(base: str, files: Sequence[str]) -> int:
    report = verify(base, files)
    for path in report.changed:
        print(f"{path}: code changed")
    for path, line, name in report.removed_docstrings:
        print(f"{path}:{line}: docstring removed from {name} ({base})")
    if report.removed_docstrings:
        print()
        print(DOCSTRING_HINT)
    return 1 if report.changed else 0
