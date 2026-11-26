import ast
import codecs
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from no_comments.detect import (
    EXTENSIONS,
    effective_shebang,
    shebang_language,
)
from no_comments.diff import _git_bytes, git
from no_comments.langs import ParseError, python, shell, typescript

DOCSTRING_HINT = (
    "删掉的 docstring 可能被 typer、click、FastAPI 等框架当作帮助文本或接口描述读取（`__doc__`），"
    "确认这些位置不依赖它，或改成显式传入 help=、description=。"
)


@dataclass
class StripReport:
    changed: list[str] = field(default_factory=list)
    directives: dict[str, list[str]] = field(default_factory=dict)
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


def changed_header(before: bytes, after: bytes, lang: str) -> str | None:
    if effective_shebang(before) != effective_shebang(after):
        return "effective shebang changed"
    if lang == "python" and python.effective_encoding(before) != python.effective_encoding(after):
        return "effective Python encoding declaration changed"
    return None


def _shebang_language(data: bytes | None) -> str | None:
    return shebang_language((data or b"").removeprefix(codecs.BOM_UTF8).split(b"\n", 1)[0])


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


def _language(path: str, base_source: bytes | None, work_source: bytes | None) -> str | None:
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
        lang = _language(path, base_bytes, work_bytes)
        if lang is None:
            continue
        try:
            if lang == "python":
                python.require_utf8(base_bytes or b"")
                python.require_utf8(work_bytes or b"")
            base_source = _decode(base_bytes, f"{path} ({base})")
            work_source = _decode(work_bytes, path)
            if base_bytes == work_bytes:
                continue
            if changed_header(base_bytes or b"", work_bytes or b"", lang):
                report.changed.append(path)
                continue
            if lang == "python":
                same = python_code(base_source) == python_code(work_source)
                if same:
                    kept = docstring_owners(work_source)
                    report.removed_docstrings += [
                        (path, line, name)
                        for name, line in docstring_owners(base_source).items()
                        if name not in kept
                    ]
            elif lang == "shell":
                same = shell.code_lines(base_source) == shell.code_lines(work_source)
            else:
                changed = typescript.changed_directives(
                    typescript.compiler_directives(base_source, lang),
                    typescript.compiler_directives(work_source, lang),
                )
                if changed:
                    report.directives[path] = changed
                    report.changed.append(path)
                    continue
                same = typescript.code_signature(base_source, lang) == typescript.code_signature(
                    work_source, lang
                )
        except ParseError as exc:
            raise ParseError(f"{path}: {exc}") from exc
        if not same:
            report.changed.append(path)
    return report


def run_verify_strip(base: str, files: Sequence[str]) -> int:
    report = verify(base, files)
    for path in report.changed:
        directives = report.directives.get(path)
        details = f" (compiler directive changed: {', '.join(directives)})" if directives else ""
        print(f"{path}: code changed{details}")
    for path, line, name in report.removed_docstrings:
        print(f"{path}:{line}: docstring removed from {name} ({base})")
    if report.removed_docstrings:
        print()
        print(DOCSTRING_HINT)
    return 1 if report.changed else 0
