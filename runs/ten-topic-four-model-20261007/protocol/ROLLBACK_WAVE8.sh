#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ] && [ "$1" != "$D/accept_completed_cells.py" ]
cp "$D/accept-baseline-wave8.py" "$1"
cmp -s "$D/accept-baseline-wave8.py" "$1"
echo byte_equal_baseline=true
set +e
"$D/../../../.venv/bin/python" "$D/check_condition_guard.py" "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_behavior_exit_status=1
