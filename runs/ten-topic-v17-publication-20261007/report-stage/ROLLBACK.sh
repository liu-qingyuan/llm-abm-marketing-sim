#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ]
case "$1" in "$D"/*) ;; *) exit 2;; esac
cp "$D/ORIGINAL_FACADE.py" "$1"
cmp -s "$D/ORIGINAL_FACADE.py" "$1"
echo byte_equal_baseline=true
set +e
"$D/../../../.venv/bin/python" "$D/check_facade.py" "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_behavior_exit_status=1
