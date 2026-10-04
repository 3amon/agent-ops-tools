"""Tests for the hook, run as Claude Code runs it: JSON on stdin, decision on stdout.

    uv run --with pytest pytest test_browser_guard.py

A stub HTTP server on an ephemeral 127.0.0.1 port stands in for Chrome's /json
endpoint, so no browser is needed.
"""
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

HOOK = Path(__file__).with_name("browser_guard.py")
EXAMPLE = json.loads(Path(__file__).with_name("policy.example.json").read_text())


class FakeChrome:
    def __init__(self):
        self.tabs = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps([{"type": "page", "url": u} for u in outer.tabs]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/json"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def chrome():
    c = FakeChrome()
    yield c
    c.stop()


@pytest.fixture
def guard(tmp_path, chrome):
    policy = dict(EXAMPLE, cdp_url=chrome.url, log=str(tmp_path / "audit.log"))
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))

    def run(tool, policy_path=path, **tool_input):
        r = subprocess.run(
            [sys.executable, str(HOOK)], capture_output=True, text=True, timeout=20,
            input=json.dumps({"tool_name": f"mcp__chrome-devtools__{tool}", "tool_input": tool_input}),
            env={"BROWSER_GUARD_POLICY": str(policy_path), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
        assert r.returncode == 0, r.stderr
        if not r.stdout.strip():
            return None                       # no output = no objection
        out = json.loads(r.stdout)["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        return out["permissionDecisionReason"]

    run.log = tmp_path / "audit.log"
    run.tmp = tmp_path
    return run


def test_interaction_allowed_when_no_guarded_tab_is_open(guard, chrome):
    chrome.tabs = ["https://docs.example.org/page"]
    assert guard("click", uid="1_2") is None
    assert guard("fill", uid="1_3", value="x") is None


def test_guarded_tab_makes_every_tab_read_only(guard, chrome):
    chrome.tabs = ["https://docs.example.org/page", "https://www.shop.example/item/42"]
    for tool in ("click", "fill", "fill_form", "type_text", "press_key", "hover", "drag",
                 "upload_file", "handle_dialog", "evaluate_script"):
        reason = guard(tool, uid="1_2")
        assert reason and "shop.example" in reason and "ALL tabs" in reason, tool
    # reading stays available
    for tool in ("take_snapshot", "take_screenshot", "wait_for", "list_pages", "close_page"):
        assert guard(tool) is None, tool


def test_subdomains_are_guarded_but_lookalikes_are_not(guard, chrome):
    chrome.tabs = ["https://login.bank.example/"]
    assert guard("click", uid="1")
    chrome.tabs = ["https://notbank.example/", "https://bank.example.evil.test/"]
    assert guard("click", uid="1") is None


def test_fails_closed_when_chrome_is_unreachable(guard, chrome):
    chrome.stop()
    reason = guard("click", uid="1")
    assert reason and "cannot reach" in reason
    assert guard("take_snapshot") is None


def test_fails_closed_without_a_policy(guard, chrome):
    missing = guard.tmp / "nope.json"
    assert "could not be loaded" in guard("click", policy_path=missing, uid="1")
    assert "could not be loaded" in guard("navigate_page", policy_path=missing, url="https://docs.example.org/")
    assert guard("take_snapshot", policy_path=missing) is None
    broken = guard.tmp / "broken.json"
    broken.write_text("{not json")
    assert "could not be loaded" in guard("fill", policy_path=broken, uid="1")


@pytest.mark.parametrize("url,denied", [
    ("https://bank.example/", True),                          # navigate: false
    ("https://online.bank.example/accounts", True),
    ("https://shop.example/item/42", False),                  # product page
    ("https://shop.example/search?q=cable", False),
    ("https://shop.example/cart", True),                      # deny_path_regex
    ("https://www.shop.example/checkout/pay", True),
    ("https://shop.example/account/settings", True),
    ("https://social.example/marketplace/item/7", False),     # allow_path_prefixes
    ("https://social.example/messages", True),
    ("https://social.example/", True),
    ("https://docs.example.org/anything", False),             # not guarded
])
def test_navigation_rules(guard, url, denied):
    for tool in ("navigate_page", "new_page"):
        assert bool(guard(tool, url=url)) is denied, (tool, url)


def test_other_tools_are_ignored(guard, tmp_path):
    r = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True,
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0 and r.stdout == ""


def test_every_call_is_logged_with_the_decision(guard, chrome):
    chrome.tabs = ["https://shop.example/item/42"]
    guard("take_snapshot")
    guard("click", uid="9_9")
    guard("navigate_page", url="https://shop.example/cart")
    lines = guard.log.read_text().splitlines()
    assert len(lines) == 3
    assert " allow " in lines[0] and "take_snapshot" in lines[0]
    assert " DENY " in lines[1] and "uid=9_9" in lines[1] and "shop.example/item/42" in lines[1]
    assert " DENY " in lines[2] and "url=https://shop.example/cart" in lines[2]
