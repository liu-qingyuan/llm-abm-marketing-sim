#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ] && [ "$1" != "$D/audit_ledger.py" ]
cp "$D/wave7/audit_ledger.py" "$1"
cmp -s "$D/wave7/audit_ledger.py" "$1"
echo byte_equal_baseline=true
set +e
"$D/../../../.venv/bin/python" "$D/wave7/check_collection.py" "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_behavior_exit_status=1
