# browser-guard

A Claude Code `PreToolUse` hook that makes a debug Chrome read-only while a
sensitive site is open.

The setup it is for: an agent drives a real Chrome (remote debugging on
`localhost:9222`) through the chrome-devtools MCP server, because headless
browsers get blocked by many sites. That Chrome profile is logged in to things.
The agent should be able to read a listing page; it should not be able to
click "Buy", send a message, or change a setting.

## Policy

- While **any** tab is on a guarded domain, every tool that can act on a page
  is denied, for every tab, not only the guarded one: `click`, `fill`,
  `fill_form`, `type_text`, `press_key`, `hover`, `drag`, `upload_file`,
  `handle_dialog`, `evaluate_script`. Navigation, snapshots, screenshots,
  waits and tab management stay available.
- `navigate_page` and `new_page` targets are checked against the site's rule:

  | Rule in the policy file | Meaning |
  |---|---|
  | `"navigate": false` | never open this site |
  | `"allow_path_prefixes": ["/marketplace"]` | only under these paths |
  | `"deny_path_regex": "^/(cart|checkout|...)"` | anywhere except matching paths |

  A domain rule covers its subdomains. `notbank.example` does not match
  `bank.example`.
- **Fail closed.** If the browser's tab list cannot be read, interaction tools
  are denied. If the policy file is missing or invalid, interaction and
  navigation tools are denied.
- **Audit log.** Every chrome-devtools call is appended to the log with the
  decision, the tool, its target, and the guarded tabs open at the time:

  ```
  2026-10-04 02:10:31 allow take_snapshot        guarded_tabs=['https://shop.example/item/42']
  2026-10-04 02:10:33 DENY  click                guarded_tabs=['https://shop.example/item/42'] uid=9_9
  2026-10-04 02:10:35 DENY  navigate_page        guarded_tabs=['https://shop.example/item/42'] url=https://shop.example/cart
  ```

Why "all tabs": the hook sees a tool name and an element id, not which tab the
click will land in. Blocking everything while a guarded tab exists is the rule
that cannot be got around by switching tabs.

## Install

1. Copy `policy.example.json` to `~/.claude/browser-guard.json` and replace the
   three example sites with your own. Set `BROWSER_GUARD_POLICY` to use another
   path.
2. Make `browser_guard.py` executable. It has a `uv run --script` shebang and no
   dependencies.
3. Add the hook to `~/.claude/settings.json` (`settings-snippet.json`):

   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "mcp__chrome-devtools__.*",
           "hooks": [
             { "type": "command", "command": "/absolute/path/to/browser_guard.py" }
           ]
         }
       ]
     }
   }
   ```

Policy file fields: `cdp_url` (default `http://127.0.0.1:9222/json`), `log`
(default `~/.claude/browser-guard.log`), and `sites`, a list of objects with
`domain`, an optional `note` that is shown to the agent in the denial, and at
most one of the three navigation rules above.

## Test

```sh
uv run --with pytest pytest
```

18 tests. They run the hook as a subprocess with the JSON Claude Code sends,
against a stub HTTP server standing in for Chrome's `/json` endpoint: read-only
while a guarded tab is open, subdomain and lookalike matching, both fail-closed
cases, 11 navigation cases, and the log format.

## Limits

- It guards the chrome-devtools MCP tools and nothing else. An agent that can
  run shell commands can talk to port 9222 directly. Close that separately
  (deny rules for the shell tool, or do not give the session a shell).
- It checks the URL the agent asks for. A permitted URL that redirects to a
  guarded page is not stopped at navigation time; once the tab is on the
  guarded domain, interaction is blocked from then on.
- The tab list is read when the hook runs. A page that navigates itself between
  the check and the action is not caught.
- If the hook receives input that is not JSON it prints nothing, which leaves
  the decision to Claude Code's normal permission flow. Claude Code always sends
  JSON, so this path is not exercised in practice.
- The hard-coded original of this hook has been in daily use. This
  configurable version was checked against the original's rules on 273 URLs
  before export (identical decisions) and by the tests here; it has not yet
  been run as the live hook.
