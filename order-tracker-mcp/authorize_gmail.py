#!/usr/bin/env python3
"""One-time Gmail OAuth flow for the order-tracker MCP server.

Needs credentials.json (an OAuth "Desktop app" client from Google Cloud
Console, with the Gmail API enabled) next to this file. Opens a browser,
asks for read-only Gmail consent, and saves token.json. The MCP server
refuses tokens with any scope beyond gmail.readonly.
"""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    creds_file = ROOT / "credentials.json"
    if not creds_file.exists():
        raise SystemExit(
            f"Missing {creds_file}.\n"
            "Create one at https://console.cloud.google.com/ :\n"
            "  1. New project (any name) -> APIs & Services -> Enable 'Gmail API'\n"
            "  2. OAuth consent screen -> External -> add yourself as a test user\n"
            "  3. Credentials -> Create credentials -> OAuth client ID -> Desktop app\n"
            "  4. Download the JSON and save it as credentials.json here"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)
    (ROOT / "token.json").write_text(creds.to_json())
    print(f"Saved {ROOT / 'token.json'} (scope: gmail.readonly)")


if __name__ == "__main__":
    main()
