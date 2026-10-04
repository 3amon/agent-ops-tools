#!/usr/bin/env bash
# Functional test for mcp-reaper.sh (Linux, needs /proc and pgrep). Takes about 5 seconds.
#
# Starts two throwaway processes that carry a unique marker in their command
# line: one spins a core, one sleeps. Runs the reaper twice with a 1-second
# sample and checks that the spinner is only marked on the first run, killed on
# the second, and that the sleeper is never touched. State and log go to a
# temporary directory, so a reaper already installed on this machine is not
# disturbed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d -t mcp-reaper-test-XXXXXX)"
MARK="mcp-reaper-selftest-$$-$RANDOM"
SPIN=""; IDLE=""
cleanup() {
  for p in "$SPIN" "$IDLE"; do
    if [[ -n "$p" ]]; then kill "$p" 2>/dev/null || true; fi
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
alive() { kill -0 "$1" 2>/dev/null; }

bash -c 'while :; do :; done' "$MARK-spin" & SPIN=$!
bash -c 'sleep 60; :' "$MARK-idle" & IDLE=$!
echo "$MARK" > "$TMP/targets"

reap() {
  XDG_RUNTIME_DIR="$TMP/run" XDG_STATE_HOME="$TMP/state" MCP_REAPER_TARGETS_FILE="$TMP/targets" \
    MCP_REAPER_SAMPLE=1 bash "$HERE/mcp-reaper.sh"
}
LOG="$TMP/state/mcp-reaper/reaper.log"
mkdir -p "$TMP/run"

reap
alive "$SPIN" || fail "spinner was killed on the first hot check"
alive "$IDLE" || fail "idle process was killed"
grep -q "hot    pid=$SPIN .*streak=1/2" "$LOG" || fail "first run did not record the streak"
grep -q "^$SPIN 1\$" "$TMP/run/mcp-reaper/hot.state" || fail "streak was not persisted"

reap
sleep 0.3
alive "$SPIN" && fail "spinner survived two consecutive hot checks"
alive "$IDLE" || fail "idle process was killed"
grep -q "KILLED pid=$SPIN " "$LOG" || fail "kill was not logged"
grep -q "pid=$IDLE " "$LOG" && fail "idle process appears in the log"
[[ -s "$TMP/run/mcp-reaper/hot.state" ]] && fail "state not cleared after the kill"

echo "PASS: spinner marked on run 1, killed on run 2; idle process untouched"
echo "--- reaper log"
sed "s/$MARK/<marker>/g" "$LOG"
