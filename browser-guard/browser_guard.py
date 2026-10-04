#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Claude Code PreToolUse hook: read-only guard for logged-in sites in a
debug Chrome (CDP on localhost:9222) driven through the chrome-devtools
MCP server.

Policy
------
* While ANY tab in the debug Chrome is on a GUARDED domain (the sites
  listed in the policy file: a bank, a shop, a social network), every
  chrome-devtools tool that can *act* on a page (click, fill, type,
  press_key, fill_form, hover, drag, upload_file, handle_dialog,
  evaluate_script) is denied — for every tab, not just the guarded one.
  Only navigation, snapshots, screenshots, waits and tab management stay
  available. Snapshots are enough to read a page.
* navigate_page / new_page URLs are checked against the site's rule:
  "navigate": false means never; "allow_path_prefixes" means only under
  those paths; "deny_path_regex" means anywhere except matching paths.
* If Chrome can't be reached, interaction tools are denied (fail closed).
* If the policy file is missing or invalid, interaction and navigation
  tools are denied (fail closed): the hook cannot know what to guard.
* Every chrome-devtools call is appended to the audit log with the
  decision and the guarded tabs open at the time.

Policy file: $BROWSER_GUARD_POLICY, default ~/.claude/browser-guard.json.
See policy.example.json. Wired in ~/.claude/settings.json (hooks.PreToolUse,
matcher mcp__chrome-devtools__.*), see settings-snippet.json.
"""
import json
import os
import re
import sys
import time
import urllib.request
from urllib.parse import urlsplit

POLICY_PATH = os.path.expanduser(
    os.environ.get("BROWSER_GUARD_POLICY", "~/.claude/browser-guard.json"))
DEFAULT_CDP = "http://127.0.0.1:9222/json"
DEFAULT_LOG = "~/.claude/browser-guard.log"

INTERACTION_TOOLS = {
    "click", "drag", "fill", "fill_form", "hover", "press_key", "type_text",
    "upload_file", "handle_dialog", "evaluate_script",
}
NAV_TOOLS = {"navigate_page", "new_page"}


class Policy:
    """Guarded sites + where the debug Chrome and the audit log are."""

    def __init__(self, raw: dict):
        self.cdp = raw.get("cdp_url", DEFAULT_CDP)
        self.log = os.path.expanduser(raw.get("log", DEFAULT_LOG))
        self.sites = {}
        for site in raw["sites"]:
            rule = dict(site)
            rule["domain"] = rule["domain"].lower().lstrip(".")
            if rule.get("deny_path_regex"):
                rule["deny_path_regex"] = re.compile(rule["deny_path_regex"], re.I)
            self.sites[rule["domain"]] = rule


def load_policy():
    """Return (policy, error). A missing or malformed file is an error, not 'no rules'."""
    try:
        with open(POLICY_PATH) as f:
            return Policy(json.load(f)), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def guarded_domain(policy: Policy, host: str):
    for d in policy.sites:
        if host == d or host.endswith("." + d):
            return d
    return None


def open_guarded_tabs(policy: Policy):
    """Return (reachable, [(domain, url), ...])."""
    try:
        with urllib.request.urlopen(policy.cdp, timeout=2) as r:
            targets = json.load(r)
    except Exception:
        return False, []
    out = []
    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url", "")
        d = guarded_domain(policy, host_of(url))
        if d:
            out.append((d, url))
    return True, out


def check_url(policy: Policy, url: str):
    """Return a denial reason for a navigation target, or None."""
    host = host_of(url)
    d = guarded_domain(policy, host)
    if not d:
        return None
    rule = policy.sites[d]
    path = urlsplit(url).path or "/"
    note = f" ({rule['note']})" if rule.get("note") else ""
    if rule.get("navigate", True) is False:
        return f"{d} is off limits.{note}"
    prefixes = rule.get("allow_path_prefixes")
    if prefixes and not any(path.startswith(p) for p in prefixes):
        return f"{d} is only allowed under {', '.join(prefixes)}.{note}"
    deny = rule.get("deny_path_regex")
    if deny and deny.search(path):
        return f"that page on {d} is off limits.{note}"
    return None


def log(path, decision, tool, detail, tabs):
    try:
        with open(path, "a") as f:
            f.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} {decision:5} {tool:20} "
                f"guarded_tabs={[u[:70] for _, u in tabs]} {detail}\n"
            )
    except Exception:
        pass


def deny(path, reason, tool, detail, tabs):
    log(path, "DENY", tool, detail, tabs)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"[browser-guard] {reason}",
        }
    }))
    sys.exit(0)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    name = payload.get("tool_name", "")
    if not name.startswith("mcp__chrome-devtools__"):
        return
    tool = name[len("mcp__chrome-devtools__"):]
    inp = payload.get("tool_input") or {}
    detail = ""
    if tool in NAV_TOOLS:
        detail = f"url={inp.get('url', '')}"
    elif tool == "evaluate_script":
        detail = "fn=" + (inp.get("function", "")[:120].replace("\n", " "))
    elif "uid" in inp:
        detail = f"uid={inp.get('uid')}"

    policy, err = load_policy()
    if policy is None:
        logfile = os.path.expanduser(DEFAULT_LOG)
        if tool in NAV_TOOLS or tool in INTERACTION_TOOLS:
            deny(logfile, f"policy file {POLICY_PATH} could not be loaded ({err}); "
                 "navigation and interaction tools are denied until it is fixed.",
                 tool, detail, [])
        log(logfile, "allow", tool, detail + " (no policy)", [])
        return

    reachable, tabs = open_guarded_tabs(policy)

    if tool in NAV_TOOLS:
        reason = check_url(policy, inp.get("url", "") or "")
        if reason:
            deny(policy.log, reason, tool, detail, tabs)

    if tool in INTERACTION_TOOLS:
        if not reachable:
            deny(policy.log, f"cannot reach the debug Chrome at {policy.cdp} to verify open "
                 "tabs; interaction tools are denied until it is reachable.",
                 tool, detail, tabs)
        if tabs:
            doms = sorted({d for d, _ in tabs})
            deny(policy.log, f"a tab on {', '.join(doms)} is open, so page interaction "
                 f"({tool}) is disabled for ALL tabs. Use navigate_page / "
                 "take_snapshot / take_screenshot / wait_for only, or close "
                 f"the guarded tab(s) first: {[u[:80] for _, u in tabs]}",
                 tool, detail, tabs)

    log(policy.log, "allow", tool, detail, tabs)


if __name__ == "__main__":
    main()
