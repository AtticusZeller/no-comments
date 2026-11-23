import os
import re
from pathlib import Path

EXTENSIONS = {".py": "python", ".pyi": "python", ".sh": "shell", ".bash": "shell"}
SHELL_INTERPRETERS = {"sh", "bash", "dash", "ksh", "ash"}
_PYTHON_INTERPRETER = re.compile(r"python[0-9.]*")


def shebang_language(first_line: bytes) -> str | None:
    if not first_line.startswith(b"#!"):
        return None
    words = first_line[2:].decode("utf-8", "replace").split()
    if words and os.path.basename(words[0]) == "env":
        words = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
    if not words:
        return None
    interpreter = os.path.basename(words[0])
    if _PYTHON_INTERPRETER.fullmatch(interpreter):
        return "python"
    if interpreter in SHELL_INTERPRETERS:
        return "shell"
    return None


def through_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(part.is_symlink() for part in (*reversed(absolute.parents), absolute))


def effective_shebang(data: bytes) -> bytes | None:
    return data.split(b"\n", 1)[0] if data.startswith(b"#!") else None


def detect_language(path: Path) -> str | None:
    if not path.is_file():
        return None
    if path.suffix in EXTENSIONS:
        return EXTENSIONS[path.suffix]
    with path.open("rb") as handle:
        return shebang_language(handle.readline(512))
