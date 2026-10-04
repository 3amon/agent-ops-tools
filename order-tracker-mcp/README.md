# order-tracker-mcp

An MCP server that lets an agent answer "has it shipped, when does it arrive,
was it refunded" for Amazon orders, without giving the agent a mailbox or a
shopping account.

Two data sources:

1. **A CSV export of your order history**, loaded into a local SQLite file.
   This is the base truth for what was ordered. Re-ingest a new export
   whenever you download one.
2. **Gmail**, for status changes since the export (shipped, out for delivery,
   delivered, delayed, refunded), with access cut down as far as it will go.

## The access limits

| Layer | Limit | Where |
|---|---|---|
| OAuth | The only scope requested is `gmail.readonly`. When the server loads the token it compares the granted scopes to that list and refuses to run if the token carries anything more. | `_gmail_service` |
| Query | Every Gmail query the server sends begins with a hard-coded `from:(amazon.com)`. There is no tool that takes a raw query. | `sync_gmail`, `gmail_search_amazon` |
| Input | The one free-text input (a search term) has every character except letters, digits, space and hyphen removed and is cut to 80 characters, so it cannot carry `from:`, `in:`, quotes or parentheses. Numeric inputs are clamped. | `_sanitize_term` |
| Result | After a message is fetched, its `From` header is parsed and the address must be at `amazon.com` or a subdomain. Anything else is dropped and counted. | `_is_amazon_sender` |

The point of the layers: a prompt-injected or confused agent calling these
tools can read mail from one sender and nothing else, and cannot send, delete
or label anything, because the token cannot do it.

## Tools

| Tool | What it does |
|---|---|
| `ingest_orders_csv(csv_path)` | Load a CSV export as base truth (replaces earlier CSV data, keeps stored email updates). Headers are matched loosely across export formats. |
| `sync_gmail(days, max_messages)` | Fetch recent order mail, classify each message by subject, store it against the order numbers it mentions. Already-seen messages are skipped. |
| `list_orders(limit, search, since)` | Orders from the CSV, newest first, with the latest email-derived status. |
| `get_order(order_id)` | CSV line items, every related email update, and the current status. |
| `recent_updates(limit)` | Latest stored updates across all orders. |
| `gmail_search_amazon(term, days, limit)` | Live search, same sender fence, nothing stored. |

## Setup

1. **CSV.** Request your order history from the retailer's data-export page.
   The file wanted is `Retail.OrderHistory.*.csv`.
2. **OAuth client.** In Google Cloud Console: new project, enable the Gmail
   API, OAuth consent screen (External, add yourself as a test user),
   Credentials, OAuth client ID, type *Desktop app*. Save the downloaded JSON as
   `credentials.json` in this directory.
3. **Authorize.** `uv run authorize_gmail.py` opens a browser, asks for
   read-only consent, and writes `token.json`.
4. **Register.**
   `claude mcp add order-tracker -- uv run --directory /path/to/order-tracker-mcp order_tracker_mcp.py`

`credentials.json`, `token.json`, `.env` and `data/` are in `.gitignore`. Do
not commit them. None of them is in this repository.

## Test

```sh
uv run pytest
```

25 tests, no network and no Google account. A fake Gmail service records the
queries the server sends and returns invented messages. The tests check that
every query starts with the sender filter even with a hostile search term,
that a token with an extra scope is refused, that a message whose display name
imitates the sender but whose real address is elsewhere is dropped by both
`sync_gmail` and the live search, and that CSV data and email updates combine
into the right current status.

## Limits

- Not tested against a live Gmail account by the test suite; it has been used
  against one mailbox.
- The sender check trusts the `From` header. Whether a forged `From` reaches
  the inbox at all is up to Gmail's own authentication checks. The server does
  not inspect DKIM or `Authentication-Results`.
- A search term may still contain the word `OR`. Because the sender filter is a
  separate leading term this can loosen the date window, not the sender; the
  post-fetch sender check is the backstop. This reasoning is not verified
  against Gmail's parser.
- Subjects and snippets of genuine order mail are returned to the model. That
  is text an outside party wrote, so treat tool output as untrusted input.
- `token.json` is stored in plain text next to the script, as the Google
  client libraries write it.
- Written against version 1.x of the MCP Python SDK (`FastMCP`); `pyproject.toml`
  pins `mcp<2`.
- Status is inferred from email subjects with a short list of patterns for one
  retailer's wording, in English.
