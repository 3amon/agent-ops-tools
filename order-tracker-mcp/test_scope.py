"""Tests for the access limits. No network, no Gmail account, no real token.

    uv run pytest

A fake Gmail service records the queries the server sends and returns invented
messages, so the tests can check what the server asks for and what it keeps.
"""
import json

import pytest

import order_tracker_mcp as m

FENCE = "from:(amazon.com) "


# ---------------------------------------------------------------- pure functions
@pytest.mark.parametrize("header,ok", [
    ("Amazon.com <shipment-tracking@amazon.com>", True),
    ("auto-confirm@amazon.com", True),
    ("Marketplace <seller@marketplace.amazon.com>", True),
    ("Amazon <A@AMAZON.COM>", True),
    ("x@notamazon.com", False),                                # suffix without the dot
    ("Amazon <a@amazon.com.evil.test>", False),                # lookalike parent domain
    ('"shipment@amazon.com" <a@evil.test>', False),            # address-shaped display name
    ('"Amazon <ship@amazon.com>" <a@evil.test>', False),       # bracketed address in the display name
    ("<ship@amazon.com> <a@evil.test>", False),                # malformed: two addresses
    ("Amazon", False),
    ("", False),
])
def test_sender_check(header, ok):
    assert m._is_amazon_sender(header) is ok


def test_search_term_cannot_carry_query_operators():
    out = m._sanitize_term('refund) OR from:(boss@example.org) {a b} "x" label:inbox in:anywhere')
    for ch in '():{}"@.':
        assert ch not in out
    assert len(m._sanitize_term("word " * 100)) <= 80
    assert m._sanitize_term(None) == ""


@pytest.mark.parametrize("subject,kind", [
    ("Delivered: Your package", "delivered"),
    ("Your package is out for delivery", "out_for_delivery"),
    ("Your Amazon.com order has shipped", "shipped"),
    ("Your refund for USB cable", "refund_or_return"),
    ("Ordered: 'USB cable'", "ordered"),
    ("A message about something else", "other"),
])
def test_classify(subject, kind):
    assert m._classify(subject) == kind


# ---------------------------------------------------------------- token scope
def test_token_with_a_broader_scope_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "token.json"
    path.write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.readonly",
                                           "https://www.googleapis.com/auth/gmail.send"]}))
    monkeypatch.setattr(m, "TOKEN_PATH", path)
    with pytest.raises(RuntimeError, match="broader scopes"):
        m._gmail_service()


def test_missing_token_is_an_error_not_a_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "TOKEN_PATH", tmp_path / "token.json")
    with pytest.raises(RuntimeError, match="not authorized"):
        m._gmail_service()
    assert "error" in m.sync_gmail()                 # tools report it instead of raising


# ---------------------------------------------------------------- fake Gmail
class FakeGmail:
    """Stands in for the object googleapiclient builds: svc.users().messages().list/get(...).execute()."""

    def __init__(self, messages):
        self.store = {x["id"]: x for x in messages}
        self.queries = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults, pageToken=None):
        self.queries.append(q)
        return _Exec({"messages": [{"id": i} for i in self.store]})

    def get(self, userId, id, format, metadataHeaders=None):
        return _Exec(self.store[id])


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


def message(mid, sender, subject, snippet=""):
    return {"id": mid, "threadId": "t" + mid, "internalDate": "1760000000000", "snippet": snippet,
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}]}}


@pytest.fixture
def gmail(tmp_path, monkeypatch):
    fake = FakeGmail([
        message("1", "Amazon.com <shipment-tracking@amazon.com>", "Shipped: order 111-1234567-1234567"),
        message("2", '"Amazon <ship@amazon.com>" <a@evil.test>', "Delivered: order 111-1234567-1234567"),
        message("3", "Amazon.com <auto-confirm@amazon.com>", "Delivered: order 111-1234567-1234567",
                snippet="Your package was left at the front door"),
    ])
    monkeypatch.setattr(m, "_gmail_service", lambda: fake)
    monkeypatch.setattr(m, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(m, "DB_PATH", tmp_path / "data" / "orders.db")
    return fake


def test_every_query_starts_with_the_sender_filter(gmail):
    m.sync_gmail(days=7)
    m.gmail_search_amazon(term="refund")
    m.gmail_search_amazon(term='x) OR from:(boss@example.org) in:anywhere "y"')
    assert len(gmail.queries) == 3
    for q in gmail.queries:
        assert q.startswith(FENCE), q
        assert q.count("from:") == 1 and q.count("(") == 1 and q.count(")") == 1, q
        assert "in:" not in q and '"' not in q


def test_sync_drops_mail_whose_real_sender_is_not_amazon(gmail):
    r = m.sync_gmail(days=7)
    assert r["non_amazon_sender_skipped"] == 1
    assert r["new_messages_stored"] == 2
    assert r["order_ids_seen"] == ["111-1234567-1234567"]
    again = m.sync_gmail(days=7)                      # idempotent
    assert again["new_messages_stored"] == 0 and again["already_known"] == 2
    # the skipped one is re-examined (it was never stored) and skipped again
    assert again["non_amazon_sender_skipped"] == 1


def test_live_search_also_rechecks_the_sender(gmail):
    out = m.gmail_search_amazon(term="order")
    assert [x["from"] for x in out] == ["Amazon.com <shipment-tracking@amazon.com>",
                                        "Amazon.com <auto-confirm@amazon.com>"]


def test_limits_are_clamped(gmail):
    m.sync_gmail(days=10 ** 9, max_messages=10 ** 9)
    assert "newer_than:3650d" in gmail.queries[-1]
    m.gmail_search_amazon(days=-5)
    assert "newer_than:1d" in gmail.queries[-1]


# ---------------------------------------------------------------- CSV + status
def test_csv_is_base_truth_and_email_gives_current_status(gmail, tmp_path):
    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "Order ID,Order Date,Product Name,ASIN,Quantity,Unit Price,Total Owed,Order Status\n"
        "111-1234567-1234567,2026-03-01T10:00:00Z,USB cable,B000000001,2,4.50,9.00,Closed\n"
        "111-1234567-1234567,2026-03-01T10:00:00Z,Wall charger,B000000002,1,12.00,12.00,Closed\n"
        "222-7654321-7654321,2026-02-10T09:00:00Z,Notebook,B000000003,1,6.25,6.25,Closed\n")
    r = m.ingest_orders_csv(str(csv_path))
    assert r["ingested_rows"] == 3 and r["distinct_orders"] == 2
    m.sync_gmail(days=7)
    order = m.get_order("111-1234567-1234567")
    assert order["csv_total"] == 21.0 and len(order["csv_items"]) == 2
    assert order["current_status"] == "delivered"     # same timestamp: delivered outranks shipped
    assert len(order["email_updates"]) == 2
    listed = m.list_orders(search="notebook")["orders"]
    assert [o["order_id"] for o in listed] == ["222-7654321-7654321"]
    assert "error" in m.get_order("999-0000000-0000000")
