#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ] && [ "$1" != "$D/summarize_call_ledger.py" ]
cp "$D/call-summary-snapshot-baseline.py" "$1"
cmp -s "$D/call-summary-snapshot-baseline.py" "$1"
echo byte_equal_baseline=true
set +e
"$D/../../../.venv/bin/python" "$D/check_snapshot_hook.py" "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_behavior_exit_status=1
