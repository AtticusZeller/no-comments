#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: evidence.sh FILE START END" >&2
  exit 2
fi
file=$1
start=$2
end=$3

echo "== blame $file:$start-$end =="
blame=$(git blame --line-porcelain -L "$start,$end" -- "$file" | awk '
  $1 ~ /^[0-9a-f]+$/ && length($1) == 40 && NF >= 3 {
    sha = $1
    if (!(sha in count)) order[++n] = sha
    count[sha]++
    next
  }
  /^summary / { sub(/^summary /, ""); subject[sha] = $0 }
  END { for (i = 1; i <= n; i++) print order[i], count[order[i]], subject[order[i]] }
')
shas=()
while read -r sha lines subject; do
  [[ -n $sha ]] || continue
  shas+=("$sha")
  day=$(git show -s --format=%ad --date=short "$sha" 2>/dev/null || echo "uncommitted")
  echo "${sha:0:10} $day $lines lines $subject"
done <<<"$blame"

echo
echo "== log -L $start,$end:$file (max 20) =="
git log -L "$start,$end:$file" --no-patch --format='%h %ad %s' --date=short -n 20 || true
while read -r sha; do
  [[ -n $sha ]] && shas+=("$sha")
done < <(git log -L "$start,$end:$file" --no-patch --format=%H -n 20 2>/dev/null || true)

echo
echo "== PR numbers in commit messages =="
prs=()
while read -r pr; do
  [[ -n $pr ]] && prs+=("$pr")
done < <(
  for sha in "${shas[@]}"; do
    git show -s --format=%B "$sha" 2>/dev/null || true
  done | grep -oE '\(#[0-9]+\)' | tr -d '()#' | sort -un || true
)
if [[ ${#prs[@]} -eq 0 ]]; then
  echo "none"
else
  printf '#%s\n' "${prs[@]}"
fi

if [[ ${#prs[@]} -gt 0 ]] && command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  for pr in "${prs[@]}"; do
    echo
    echo "== PR #$pr =="
    if body=$(gh pr view "$pr" --json title,body -q '.title, .body' 2>/dev/null); then
      awk 'NR <= 41' <<<"$body"
    else
      echo "unavailable"
    fi
  done
fi
