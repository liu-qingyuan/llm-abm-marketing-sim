#!/bin/sh
set -eu
E=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ]
[ "$1" = "$E/scratch-head.json" ]
cp "$E/BEFORE.json" "$1"
cmp -s "$E/BEFORE.json" "$1"
echo byte_equal_baseline=true
set +e
"$E/../../.venv/bin/python" "$E/check_head_record.py" "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_behavior_exit_status=1
