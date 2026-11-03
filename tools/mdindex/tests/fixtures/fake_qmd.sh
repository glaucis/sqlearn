#!/bin/sh
echo "$*" >> "$FAKE_QMD_LOG"
if [ -n "$FAKE_QMD_FAIL" ]; then
  case "$*" in *"$FAKE_QMD_FAIL"*) echo "fake failure" >&2; exit 1;; esac
fi
exit 0
