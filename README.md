# agent-ops-tools

Four small pieces from running coding agents every day on my own machines.
Three are guard rails and one is a measurement. They share one idea:

1. **Limit what the agent can do**, at a layer the agent does not control (a
   hook, an OAuth scope, a process supervisor), instead of asking it to behave.
2. **Fail closed.** When the guard cannot tell whether an action is safe, the
   action is refused.
3. **Keep an audit trail.** Every decision is written to a plain log.

| Directory | What it is | Limit | When it cannot tell | Audit trail |
|---|---|---|---|---|
| [`browser-guard/`](browser-guard/) | Claude Code `PreToolUse` hook for the chrome-devtools MCP server | While any tab is on a guarded site, the browser is read-only for every tab; navigation to guarded sites follows per-site rules | Denies: browser unreachable, or policy file unreadable | One line per browser tool call with the decision |
| [`mcp-reaper/`](mcp-reaper/) | systemd user timer that kills MCP servers stuck at full CPU while idle | Only processes matching a list of command-line patterns, only after two consecutive hot samples | Leaves the process alone | One line per hot sample and per kill |
| [`order-tracker-mcp/`](order-tracker-mcp/) | MCP server that answers "where is my order" from a CSV export plus Gmail | Read-only OAuth scope; every query fenced to one sender domain; sender checked again after fetch | Refuses to use a token that carries any other scope | Each stored message keeps sender, date and message id |
| [`thinking-strip-experiment/`](thinking-strip-experiment/) | A/B harness: keep or strip a local model's "thinking" between tool rounds | n/a | n/a | Every trial's full transcript is saved |

```
                 agent wants to act
                        │
            ┌───────────▼───────────┐
            │ guard outside the      │   browser-guard: hook process
            │ agent's control        │   order-tracker: OAuth scope + query fence
            └───────────┬───────────┘   mcp-reaper: timer + /proc
        can it verify the action is allowed?
              │ yes            │ no / cannot tell
              ▼                ▼
           allow             deny            both written to a log
```

## What is demonstrated, with numbers

- **browser-guard**: 204 lines, standard library only. 10 page-interaction
  tools are blocked while a guarded tab is open. 18 tests drive the hook the
  way Claude Code does (JSON on stdin) against a stub of Chrome's tab list.
- **mcp-reaper**: 87 lines of bash. A process must be above 15% of one core in
  two 8-second samples taken 150 seconds apart before it is killed. A
  5-second functional test spawns a spinning and a sleeping process and
  checks that only the spinner dies, and only on the second run.
- **order-tracker-mcp**: 540 lines, 6 tools, 1 OAuth scope
  (`gmail.readonly`). 25 tests with a fake Gmail service check that every
  query starts with the sender filter and that mail from a spoofed sender is
  dropped.
- **thinking-strip-experiment**: 90 trials (3 scenarios x 2 conditions x 15
  repetitions) on a local model. Stripping the model's thinking between tool
  rounds cost 0.46 extra rounds on one scenario (bootstrap 95% interval 0.19
  to 0.73) and nothing measurable on the other two. See that README for what
  15 repetitions can and cannot show.

## Run the tests

Each directory is independent. Everything Python runs through
[uv](https://docs.astral.sh/uv/).

```sh
(cd browser-guard     && uv run --with pytest pytest)      # 18 passed
(cd mcp-reaper        && ./test-reaper.sh)                 # PASS, about 5 s, Linux only
(cd order-tracker-mcp && uv run pytest)                    # 25 passed
(cd thinking-strip-experiment && python3 analyze.py)       # re-derives the README numbers
```

## Status and limits

These were written for one person's setup (Linux desktop, Claude Code, a
debug Chrome on port 9222). They are small on purpose and each README lists
what the tool does not cover. Two things to know up front:

- The guards narrow what an agent can do through one channel. They are not a
  sandbox. An agent with a shell can reach the same browser or mailbox another
  way unless that is restricted too.
- `browser-guard` here reads its site list from a policy file. The version in
  daily use had the list hard-coded; the configurable version is covered by the
  tests but has not yet replaced the original as the live hook.

## Not included

- Credentials, OAuth tokens, the order database and any real mail.
- The author's own site list for `browser-guard` (the example policy uses
  reserved `.example` domains).
- The production assistant whose tool surface the experiment imitates. The
  experiment uses canned tools with the same shape.

## Licence

MIT, see `LICENSE`. Copyright 2026 Eamon White.
