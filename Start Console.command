#!/usr/bin/env bash
# Double-click this file to set up (first time) and launch the Candidate
# Sourcing Console. If macOS warns the file is from an "unidentified
# developer" the first time, right-click it and choose Open instead.
cd "$(dirname "${BASH_SOURCE[0]}")"
bash scripts/start_console.sh
status=$?
echo
read -r -p "Press Enter to close this window... "
exit $status
