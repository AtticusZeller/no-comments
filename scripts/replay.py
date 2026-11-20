import argparse
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from no_comments.allow import is_allowed
from no_comments.cli import EXTENSIONS, EXTRACTORS, shebang_language
from no_comments.langs import ParseError

FINDING = re.compile(r"^(.*?):(\d+):(\d+): (NC00\d) (comment|docstring) not allowed: ")
SLOW_SECONDS = 2.0


def git(cwd, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return proc.stdout


def language(path, source):
    return EXTENSIONS.get(Path(path).suffix) or shebang_language(source.split("\n", 1)[0].encode())


def comments_at(cwd, rev, paths):
    found = {}
    for path in paths:
        try:
            source = git(cwd, "show", f"{rev}:{path}").decode("utf-8-sig")
        except (RuntimeError, UnicodeDecodeError):
            continue
        lang = language(path, source)
        if lang is None:
            continue
        try:
            found[path] = (lang, EXTRACTORS[lang](source))
        except ParseError:
            continue
    return found


HUNK = re.compile(rb"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def rename_sources(cwd, parent, commit):
    fields = git(cwd, "diff", "-M", "--name-status", "-z", parent, commit).decode().split("\0")
    sources, i = {}, 0
    while i < len(fields) and fields[i]:
        if fields[i][0] in "RC":
            sources[fields[i + 2]] = fields[i + 1]
            i += 3
        else:
            i += 2
    return sources


def added_lines(cwd, parent, commit, path, source):
    if source is None:
        total = len(git(cwd, "show", f"{commit}:{path}").splitlines())
        return set(range(1, total + 1))
    out = git(cwd, "diff", "--no-ext-diff", "-U0", f"{parent}:{source}", f"{commit}:{path}")
    lines = set()
    for start, count in HUNK.findall(out):
        lines.update(range(int(start), int(start) + int(count or 1)))
    return lines


def expected_counts(old, new, added):
    surplus = collections.Counter(c.key for _, items in new.values() for c in items)
    surplus.subtract(c.key for _, items in old.values() for c in items)
    allowed = {c.key for path, (lang, items) in new.items() for c in items if is_allowed(lang, c)}
    on_added = collections.Counter(
        c.key
        for path, (_, items) in new.items()
        for c in items
        if any(n in added[path] for n in c.lines)
    )
    return {
        key: min(n, on_added[key])
        for key, n in surplus.items()
        if n > 0 and on_added[key] and key not in allowed
    }


def changed(cwd, parent, commit):
    old, new = [], []
    fields = (
        git(cwd, "diff", "--no-renames", "--name-status", "-z", parent, commit).decode().split("\0")
    )
    for status, path in zip(fields[0::2], fields[1::2], strict=False):
        if status != "A":
            old.append(path)
        if status != "D":
            new.append(path)
    return old, new


def replay_commit(tool, work, commit, parent):
    old_paths, new_paths = changed(work, parent, commit)
    git(work, "checkout", "-q", "-f", "--detach", commit)
    files = [p for p in new_paths if (work / p).is_file()]
    record = {"commit": commit[:10], "files": len(files), "findings": [], "mismatches": []}
    if not files:
        return record
    env = {**os.environ, "PRE_COMMIT_FROM_REF": parent, "PRE_COMMIT_TO_REF": commit}
    start = time.perf_counter()
    proc = subprocess.run(
        [tool, "check", *files], cwd=work, env=env, capture_output=True, text=True
    )
    record["seconds"] = round(time.perf_counter() - start, 3)
    record["exit"] = proc.returncode
    record["warnings"] = [line for line in proc.stderr.splitlines() if line.strip()]
    new = comments_at(work, commit, new_paths)
    by_position = {(path, c.line, c.col): c for path, (_, items) in new.items() for c in items}
    reported = collections.Counter()
    for line in proc.stdout.splitlines():
        match = FINDING.match(line)
        if not match:
            continue
        comment = by_position.get((match[1], int(match[2]), int(match[3])))
        record["findings"].append(line)
        if comment is None:
            record["mismatches"].append({"unmatched_finding": line})
        else:
            reported[comment.key] += 1
    sources = rename_sources(work, parent, commit)
    old_names = set(old_paths)
    added = {
        path: added_lines(
            work, parent, commit, path, sources.get(path, path if path in old_names else None)
        )
        for path in new
    }
    expected = expected_counts(comments_at(work, parent, old_paths), new, added)
    for key in set(expected) | set(reported):
        if reported[key] != expected.get(key, 0):
            record["mismatches"].append(
                {
                    "kind": key[0].value,
                    "text": key[1][:120],
                    "reported": reported[key],
                    "expected": expected.get(key, 0),
                }
            )
    return record


def replay_repo(tool, repo, limit):
    repo = Path(repo).resolve()
    commits = git(repo, "rev-list", "--no-merges", f"-n{limit}", "HEAD").decode().split()
    records = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        git(repo, "worktree", "add", "-q", "--detach", str(work), "HEAD")
        try:
            for commit in commits:
                parents = git(repo, "rev-list", "--parents", "-n1", commit).decode().split()[1:]
                if parents:
                    records.append(replay_commit(tool, work, commit, parents[0]))
        finally:
            git(repo, "worktree", "remove", "--force", str(work), check=False)
    return records


def summarize(name, records):
    findings = [f for r in records for f in r["findings"]]
    return {
        "repo": name,
        "commits": len(records),
        "NC001": sum(" NC001 " in f for f in findings),
        "NC002": sum(" NC002 " in f for f in findings),
        "mismatch": sum(len(r["mismatches"]) for r in records),
        "exit2": sum(r.get("exit") == 2 for r in records),
        "warning": sum(len(r.get("warnings", [])) for r in records),
        "slow": sum(r.get("seconds", 0) > SLOW_SECONDS for r in records),
        "max_s": max((r.get("seconds", 0) for r in records), default=0),
    }


def main():
    parser = argparse.ArgumentParser(prog="replay")
    parser.add_argument("repos", nargs="+", metavar="REPO")
    parser.add_argument("--commits", type=int, default=150)
    parser.add_argument("--out", type=Path, default=Path("replay-out"))
    parser.add_argument("--tool", default=str(Path(sys.executable).parent / "no-comments"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for repo in args.repos:
        name = Path(repo).resolve().name
        records = replay_repo(args.tool, repo, args.commits)
        (args.out / f"{name}.json").write_text(json.dumps(records, ensure_ascii=False, indent=1))
        rows.append(summarize(name, records))
        row = rows[-1]
        print("  ".join(f"{k}={v}" for k, v in row.items()), flush=True)
    failed = any(r["mismatch"] or r["exit2"] or r["warning"] or r["slow"] for r in rows)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
