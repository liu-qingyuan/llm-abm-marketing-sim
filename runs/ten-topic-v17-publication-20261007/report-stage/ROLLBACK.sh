#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ]
case "$1" in "$D"/*) ;; *) exit 2;; esac
git -C "$D/../../.." show ba8977d:src/llm_abm_sim/concurrent_robustness_report.py > "$1"
expected=d40bc38021cc0ea205cb4ba0f839ee0eec6e50caa1e93d391628e344f78114b4
actual=$(shasum -a 256 "$1" | awk '{print $1}')
[ "$actual" = "$expected" ]
echo byte_equal_baseline=true
set +e
"$D/../../../.venv/bin/python" "$D/check_facade.py" "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_behavior_exit_status=1
