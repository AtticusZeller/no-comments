#!/usr/bin/env bash
# shellcheck disable=SC2086
set -euo pipefail
arr=(a b c)
echo "args: $# items: ${#arr[@]}"
echo "a # b" 'c # d' x#y
name="file#1"
echo ${name#file}
echo $((16#ff))
cat <<EOF2
# inside heredoc
EOF2
cat <<'RAW'
# inside quoted heredoc
RAW
