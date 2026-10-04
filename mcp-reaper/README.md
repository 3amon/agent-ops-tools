# mcp-reaper

Kills MCP server processes that sit at full CPU while doing nothing.

Some MCP servers fail to sleep when idle and spin a core for hours (the one
that prompted this was a KiCad interface process). The agent session that
started them does not notice. This script, run from a systemd user timer,
measures each matching process and kills the ones that stay hot.

## How it decides

1. Find processes whose command line matches one of the target patterns
   (`pgrep -f`).
2. Measure real CPU use over 8 seconds from `/proc/<pid>/stat` (utime + stime).
3. Above 15% of one core counts as hot. The pid and its streak are saved.
4. A process that is hot on two consecutive runs is sent SIGTERM. With the
   timer at 150 seconds, that means it was hot in two samples 2.5 minutes
   apart. A tool call that is actually working lasts seconds, not minutes.

A process that cools down between runs loses its streak. A process that
cannot be read (already exited) is skipped.

Every hot sample and every kill is appended to
`$XDG_STATE_HOME/mcp-reaper/reaper.log`:

```
2026-10-04 01:59:52 hot    pid=1960829 cpu=100% streak=1/2
2026-10-04 01:59:54 KILLED pid=1960829 cpu=100% after=2x  <command line, first 80 chars>
```

## Install

```sh
install -D mcp-reaper.sh ~/bin/mcp-reaper.sh
cp mcp-reaper.service mcp-reaper.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mcp-reaper.timer
```

The unit runs `%h/bin/mcp-reaper.sh`; edit `ExecStart` if you put it elsewhere.

Targets: edit `TARGETS` in the script, or list one extended regex per line in
`~/.config/mcp-reaper/targets` (or the file named by
`MCP_REAPER_TARGETS_FILE`), which replaces the built-in list. Keep patterns
specific: anything whose command line matches can be killed.

`MCP_REAPER_THRESHOLD` (percent of one core, default 15), `MCP_REAPER_SAMPLE`
(seconds, default 8) and `MCP_REAPER_NEEDED` (consecutive hot runs, default 2)
override the constants.

## Test

```sh
./test-reaper.sh
```

Linux only, about 5 seconds. It starts a spinning process and a sleeping one
with a unique marker, runs the reaper twice with a 1-second sample, and checks
that the spinner is marked on the first run, killed on the second, and that the
sleeper never appears in the log. It uses a temporary state and log directory,
so it does not disturb an installed reaper.

## Limits

- Linux only (`/proc`, `pgrep`, systemd).
- It samples twice, 150 seconds apart. A server that happens to be busy with
  real work at both sample times would be killed. The threshold and the
  two-run rule make that unlikely for request-driven servers; it is not
  impossible.
- SIGTERM only. A process that ignores it stays, and is logged as killed only
  if the signal was delivered.
- Killing the server does not restart it. The MCP client has to reconnect.
- The fix belongs in the server. This is a workaround for servers you do not
  maintain.
