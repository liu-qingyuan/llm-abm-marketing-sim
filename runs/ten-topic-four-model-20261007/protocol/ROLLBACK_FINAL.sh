#!/bin/sh
set -eu
D=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" = 1 ] && [ "$1" != "$D/final_corroboration.py" ]
cp "$D/final-corroboration-baseline.py" "$1"
cmp -s "$D/final-corroboration-baseline.py" "$1"
echo byte_equal_baseline=true
set +e
"$D/../../../.venv/bin/ruff" check --select F "$1"
status=$?
set -e
[ "$status" = 1 ]
echo restored_baseline_unused_import_status=1
