#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=${1:?scratch file required}
case "$TARGET" in */rollback-audit-test.py) ;; *) exit 2;; esac
cp "$ROOT/AUDIT_EXECUTED.py" "$TARGET"
cmp "$ROOT/AUDIT_EXECUTED.py" "$TARGET"
printf 'ROLLBACK restored original acceptance source bytes\n'
