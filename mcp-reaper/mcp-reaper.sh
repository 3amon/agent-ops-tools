#!/usr/bin/env bash
# mcp-reaper — kills MCP backend processes that idle-spin a CPU core.
#
# Some MCP servers (notably the KiCad interface) fail to sleep when idle and
# instead use a whole core doing nothing. This reaper samples their real
# instantaneous CPU use and kills any that stay hot across two consecutive
# runs (~2x the timer interval), which reliably means "stuck/idle-spinning"
# rather than "handling a live tool call" (those last seconds, not minutes).
#
# Add patterns to TARGETS to cover more offenders, or list them one per line in
# $MCP_REAPER_TARGETS_FILE (default ~/.config/mcp-reaper/targets), which replaces
# the built-in list. Keep them specific enough not to match unrelated processes.
set -euo pipefail

# Regexes (pgrep -f, matched against the full command line).
TARGETS=(
  'KiCAD-MCP-Server/python/kicad_interface\.py'
)
TARGETS_FILE="${MCP_REAPER_TARGETS_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/mcp-reaper/targets}"
if [[ -r "$TARGETS_FILE" ]]; then
  mapfile -t TARGETS < <(grep -vE '^[[:space:]]*(#|$)' "$TARGETS_FILE" || true)
fi

THRESHOLD="${MCP_REAPER_THRESHOLD:-15}"   # % of one core; a healthy idle MCP server sits near 0.
SAMPLE="${MCP_REAPER_SAMPLE:-8}"          # seconds to measure instantaneous CPU over.
NEEDED="${MCP_REAPER_NEEDED:-2}"          # consecutive hot checks before we kill.

STATE_DIR="${XDG_RUNTIME_DIR:-/tmp}/mcp-reaper"
STATE="$STATE_DIR/hot.state"        # lines: "<pid> <consecutive-hot-count>"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/mcp-reaper"
LOG="$LOG_DIR/reaper.log"
mkdir -p "$STATE_DIR" "$LOG_DIR"

CLK=$(getconf CLK_TCK)

# Sum of utime+stime (clock ticks) for a pid, robust to spaces in comm.
proc_ticks() {
  local pid=$1 stat rest
  stat=$(< "/proc/$pid/stat") || return 1
  rest=${stat#*") "}            # drop "pid (comm) ", leaving fields from state
  read -ra f <<< "$rest"
  echo $(( ${f[11]} + ${f[12]} ))   # utime + stime
}

# Instantaneous CPU% (of one core) for a pid over $SAMPLE seconds.
cpu_pct() {
  local pid=$1 t1 t2
  t1=$(proc_ticks "$pid") || return 1
  sleep "$SAMPLE"
  t2=$(proc_ticks "$pid") || return 1
  awk -v d=$(( t2 - t1 )) -v clk="$CLK" -v s="$SAMPLE" \
    'BEGIN { printf "%d", (d/clk)/s*100 }'
}

declare -A prev=()
if [[ -f "$STATE" ]]; then
  while read -r pid n; do [[ -n "${pid:-}" ]] && prev[$pid]=$n; done < "$STATE"
fi

declare -A next=()
now=$(date '+%Y-%m-%d %H:%M:%S')

for re in "${TARGETS[@]}"; do
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    pct=$(cpu_pct "$pid" 2>/dev/null) || continue   # process may have exited
    if (( pct >= THRESHOLD )); then
      count=$(( ${prev[$pid]:-0} + 1 ))
      if (( count >= NEEDED )); then
        cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | cut -c1-80)
        if kill "$pid" 2>/dev/null; then
          echo "$now KILLED pid=$pid cpu=${pct}% after=${count}x  $cmd" >> "$LOG"
        fi
        # not carried into next state — it's gone
      else
        next[$pid]=$count
        echo "$now hot    pid=$pid cpu=${pct}% streak=${count}/${NEEDED}" >> "$LOG"
      fi
    fi
  done < <(pgrep -f "$re" || true)
done

# Persist streaks for still-living hot pids.
: > "$STATE"
for pid in "${!next[@]}"; do
  kill -0 "$pid" 2>/dev/null && echo "$pid ${next[$pid]}" >> "$STATE"
done
