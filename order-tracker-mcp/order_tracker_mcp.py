#!/usr/bin/env python3
"""Order-tracker MCP server: Amazon order CSV as base truth + Gmail for live updates.

Gmail access is deliberately limited:
  - OAuth scope is gmail.readonly only (enforced again at load time).
  - Every Gmail query is prefixed with a hardcoded from:(amazon.com) filter;
    tool inputs are sanitized so they cannot inject query operators.
  - After fetching, the From header is re-verified to be an @amazon.com sender.
"""

import csv
import json
import re
import base64
import sqlite3
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "orders.db"
TOKEN_PATH = ROOT / "token.json"
CREDENTIALS_PATH = ROOT / "credentials.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# The fence: every Gmail query starts with this and user terms are sanitized
# so they can't close the paren / add OR clauses to widen it.
AMAZON_FROM = "from:(amazon.com)"

ORDER_ID_RE = re.compile(r"\b(D?\d{2,3}-\d{7}-\d{7})\b")

mcp = FastMCP(name="order-tracker")


# ---------------------------------------------------------------- database

def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS order_items(
            order_id TEXT, order_date TEXT, order_date_iso TEXT,
            product_name TEXT, asin TEXT, quantity TEXT,
            unit_price TEXT, total TEXT, currency TEXT,
            order_status TEXT, shipment_status TEXT, ship_date TEXT,
            tracking TEXT, website TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
        CREATE TABLE IF NOT EXISTS email_updates(
            message_id TEXT PRIMARY KEY, thread_id TEXT,
            date TEXT, from_addr TEXT, subject TEXT,
            kind TEXT, order_ids TEXT, snippet TEXT
        );
        CREATE TABLE IF NOT EXISTS email_orders(
            message_id TEXT, order_id TEXT,
            PRIMARY KEY(message_id, order_id)
        );
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """
    )
    return conn


def _num(s):
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s))
    return float(m.group().replace(",", "")) if m else None


def _iso_date(s: str) -> str:
    s = (s or "").strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


# Fuzzy CSV header matching: normalized header -> canonical field.
# Covers the Privacy Central Retail.OrderHistory export plus older
# order-report formats.
_HEADER_MAP = {
    "order_id": ["orderid"],
    "order_date": ["orderdate"],
    "product_name": ["productname", "title", "itemname", "description"],
    "asin": ["asin", "asinisbn"],
    "quantity": ["quantity", "qty", "itemquantity", "originalquantity"],
    "unit_price": ["unitprice", "purchasepriceperunit", "purchaseprice", "listpriceperunit"],
    "total": ["totalowed", "totalamount", "itemtotal", "totalcharged", "shipmentitemsubtotal"],
    "currency": ["currency"],
    "order_status": ["orderstatus"],
    "shipment_status": ["shipmentstatus"],
    "ship_date": ["shipdate", "shipmentdate"],
    "tracking": ["carriernametrackingnumber", "trackingnumber", "carriernameandtrackingnumber"],
    "website": ["website"],
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").lower())


@mcp.tool()
def ingest_orders_csv(csv_path: str) -> dict:
    """Load an Amazon order-history CSV as the base source of truth.

    Replaces all previously ingested CSV data (email updates are kept).
    Accepts the Privacy Central "Your Orders" export
    (Retail.OrderHistory.*.csv) or older order-report CSVs; columns are
    matched fuzzily.

    Args:
        csv_path: Absolute path to the CSV file.
    """
    path = Path(csv_path).expanduser()
    if not path.exists():
        return {"error": f"File not found: {path}"}

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"error": "CSV has no header row"}
        colmap = {}
        for field, aliases in _HEADER_MAP.items():
            for alias in aliases:  # alias order = priority
                hit = next((h for h in reader.fieldnames if _norm_header(h) == alias), None)
                if hit:
                    colmap[field] = hit
                    break
        if "order_id" not in colmap:
            return {
                "error": "Could not find an Order ID column",
                "headers_seen": reader.fieldnames,
            }
        rows = []
        for raw in reader:
            get = lambda k: (raw.get(colmap[k]) or "").strip() if k in colmap else ""
            order_date = get("order_date")
            rows.append(
                (
                    get("order_id"), order_date, _iso_date(order_date),
                    get("product_name"), get("asin"), get("quantity"),
                    get("unit_price"), get("total"), get("currency"),
                    get("order_status"), get("shipment_status"),
                    get("ship_date"), get("tracking"), get("website"),
                )
            )

    conn = _db()
    with conn:
        conn.execute("DELETE FROM order_items")
        conn.executemany(
            "INSERT INTO order_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('last_ingest', ?)",
            (json.dumps({
                "path": str(path),
                "rows": len(rows),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }),),
        )
    n_orders = conn.execute(
        "SELECT COUNT(DISTINCT order_id) FROM order_items"
    ).fetchone()[0]
    conn.close()
    return {
        "ingested_rows": len(rows),
        "distinct_orders": n_orders,
        "columns_matched": colmap,
        "note": "Previous CSV data replaced; email updates preserved.",
    }


# ------------------------------------------------------------- gmail layer

def _gmail_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if not TOKEN_PATH.exists():
        raise RuntimeError(
            "Gmail not authorized. Run `uv run authorize_gmail.py` in "
            f"{ROOT} first (needs credentials.json — see README)."
        )
    token = json.loads(TOKEN_PATH.read_text())
    granted = set((token.get("scopes") or []))
    if not granted.issubset(set(SCOPES)):
        raise RuntimeError(
            f"token.json has broader scopes than allowed ({granted}); "
            "delete it and re-run authorize_gmail.py."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
        else:
            raise RuntimeError("Gmail token invalid — re-run authorize_gmail.py.")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _sanitize_term(term: str) -> str:
    """Strip anything that could act as a Gmail query operator."""
    return re.sub(r"[^A-Za-z0-9 \-]", " ", term or "").strip()[:80]


def _is_amazon_sender(from_header: str) -> bool:
    # parseaddr returns the real address even when the display name contains an
    # address-shaped string in angle brackets (a spoofed "From" display name).
    addr = parseaddr(from_header or "")[1].strip().lower()
    if "@" not in addr:
        return False
    domain = addr.rsplit("@", 1)[-1]
    return domain == "amazon.com" or domain.endswith(".amazon.com")


_KIND_PATTERNS = [
    ("delivered", r"\bdelivered\b"),
    ("out_for_delivery", r"out for delivery"),
    ("delayed", r"\bdelay|running late|delivery date has changed"),
    ("cancelled", r"\bcancel"),
    ("refund_or_return", r"\brefund|\breturn\b"),
    ("shipped", r"\bshipped\b|has shipped|on its way|on the way"),
    ("arriving", r"\barriving\b"),
    ("ordered", r"^ordered\b|order confirmation|your amazon\.com order|thanks for your order|order placed"),
]

# Kinds that represent a shipment state, ranked for tie-breaks on same-day emails.
_STATUS_RANK = {
    "ordered": 1, "arriving": 2, "shipped": 3, "delayed": 4,
    "out_for_delivery": 5, "delivered": 6, "cancelled": 7, "refund_or_return": 8,
}


def _classify(subject: str) -> str:
    s = (subject or "").lower()
    for kind, pat in _KIND_PATTERNS:
        if re.search(pat, s):
            return kind
    return "other"


def _headers(payload) -> dict:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _body_text(payload) -> str:
    chunks = []

    def walk(part):
        data = part.get("body", {}).get("data")
        mime = part.get("mimeType", "")
        if data and mime.startswith("text/"):
            text = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            if mime == "text/html":
                text = re.sub(r"<[^>]+>", " ", text)
            chunks.append(text)
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return "\n".join(chunks)


@mcp.tool()
def sync_gmail(days: int = 30, max_messages: int = 100) -> dict:
    """Fetch recent Amazon order emails from Gmail and store their status
    updates (shipped / delivered / refund...) alongside the CSV data.

    Only reads mail matching a hardcoded from:(amazon.com) filter with the
    read-only Gmail scope. Already-seen messages are skipped, so this is
    cheap to call repeatedly.

    Args:
        days: How far back to look (Gmail newer_than filter).
        max_messages: Cap on messages examined per call.
    """
    days = max(1, min(int(days), 3650))
    max_messages = max(1, min(int(max_messages), 500))
    try:
        svc = _gmail_service()
    except Exception as e:
        return {"error": str(e)}

    query = f"{AMAZON_FROM} newer_than:{days}d"
    msg_ids, page_token = [], None
    while len(msg_ids) < max_messages:
        resp = svc.users().messages().list(
            userId="me", q=query, pageToken=page_token,
            maxResults=min(100, max_messages - len(msg_ids)),
        ).execute()
        msg_ids += [m["id"] for m in resp.get("messages", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    conn = _db()
    known = {
        r[0] for r in conn.execute(
            "SELECT message_id FROM email_updates"
        ).fetchall()
    }
    new_ids = [i for i in msg_ids if i not in known]

    by_kind, orders_seen, skipped_sender = {}, set(), 0
    for mid in new_ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        payload = msg.get("payload", {})
        hdrs = _headers(payload)
        if not _is_amazon_sender(hdrs.get("from", "")):
            skipped_sender += 1
            continue
        subject = hdrs.get("subject", "")
        kind = _classify(subject)
        date = datetime.fromtimestamp(
            int(msg.get("internalDate", 0)) / 1000, tz=timezone.utc
        ).isoformat(timespec="seconds")
        ids = sorted(set(
            ORDER_ID_RE.findall(subject) + ORDER_ID_RE.findall(_body_text(payload))
        ))
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO email_updates VALUES (?,?,?,?,?,?,?,?)",
                (mid, msg.get("threadId"), date, hdrs.get("from", ""),
                 subject, kind, json.dumps(ids), msg.get("snippet", "")),
            )
            for oid in ids:
                conn.execute(
                    "INSERT OR IGNORE INTO email_orders VALUES (?,?)", (mid, oid)
                )
        by_kind[kind] = by_kind.get(kind, 0) + 1
        orders_seen.update(ids)
    conn.close()
    return {
        "matched_in_gmail": len(msg_ids),
        "new_messages_stored": len(new_ids) - skipped_sender,
        "already_known": len(msg_ids) - len(new_ids),
        "non_amazon_sender_skipped": skipped_sender,
        "by_kind": by_kind,
        "order_ids_seen": sorted(orders_seen),
    }


@mcp.tool()
def gmail_search_amazon(term: str = "", days: int = 90, limit: int = 20) -> list:
    """Live search of Amazon emails in Gmail (not stored). The from:(amazon.com)
    filter is always applied; the term is sanitized and cannot widen the search
    beyond Amazon senders.

    Args:
        term: Words to search for (product name, 'refund', order number...).
        days: How far back to look.
        limit: Max results.
    """
    days = max(1, min(int(days), 3650))
    limit = max(1, min(int(limit), 50))
    try:
        svc = _gmail_service()
    except Exception as e:
        return [{"error": str(e)}]

    query = f"{AMAZON_FROM} newer_than:{days}d {_sanitize_term(term)}".strip()
    resp = svc.users().messages().list(
        userId="me", q=query, maxResults=limit
    ).execute()
    out = []
    for m in resp.get("messages", []):
        msg = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        hdrs = _headers(msg.get("payload", {}))
        if not _is_amazon_sender(hdrs.get("from", "")):
            continue
        subject = hdrs.get("subject", "")
        out.append({
            "date": datetime.fromtimestamp(
                int(msg.get("internalDate", 0)) / 1000, tz=timezone.utc
            ).isoformat(timespec="seconds"),
            "from": hdrs.get("from", ""),
            "subject": subject,
            "kind": _classify(subject),
            "order_ids": sorted(set(ORDER_ID_RE.findall(subject + " " + msg.get("snippet", "")))),
            "snippet": msg.get("snippet", ""),
        })
    return out


# ------------------------------------------------------------ query tools

def _latest_status(conn, order_id: str):
    row = conn.execute(
        """SELECT e.kind, e.date, e.subject FROM email_updates e
           JOIN email_orders eo ON eo.message_id = e.message_id
           WHERE eo.order_id = ? AND e.kind != 'other'
           ORDER BY e.date DESC,
                    CASE e.kind {} ELSE 0 END DESC
           LIMIT 1""".format(
            " ".join(f"WHEN '{k}' THEN {v}" for k, v in _STATUS_RANK.items())
        ),
        (order_id,),
    ).fetchone()
    return dict(row) if row else None


@mcp.tool()
def list_orders(limit: int = 20, search: str = "", since: str = "") -> dict:
    """List orders from the ingested CSV, newest first, with the latest
    email-derived status attached when known.

    Args:
        limit: Max orders to return.
        search: Substring match on product names (case-insensitive).
        since: Only orders on/after this date (YYYY-MM-DD).
    """
    limit = max(1, min(int(limit), 200))
    conn = _db()
    meta = conn.execute("SELECT value FROM meta WHERE key='last_ingest'").fetchone()
    where, params = ["1=1"], []
    if search:
        where.append("EXISTS (SELECT 1 FROM order_items i2 WHERE i2.order_id = i.order_id AND i2.product_name LIKE ?)")
        params.append(f"%{search}%")
    if since:
        where.append("i.order_date_iso >= ?")
        params.append(since)
    rows = conn.execute(
        f"""SELECT i.order_id, MAX(i.order_date_iso) AS date,
                   COUNT(*) AS items, GROUP_CONCAT(i.product_name, ' | ') AS products,
                   MAX(i.order_status) AS order_status,
                   MAX(i.shipment_status) AS shipment_status
            FROM order_items i WHERE {' AND '.join(where)}
            GROUP BY i.order_id ORDER BY date DESC LIMIT ?""",
        params + [limit],
    ).fetchall()
    orders = []
    for r in rows:
        d = dict(r)
        d["products"] = (d["products"] or "")[:300]
        email = _latest_status(conn, r["order_id"])
        if email:
            d["email_status"] = email
        orders.append(d)
    conn.close()
    return {
        "base_csv": json.loads(meta[0]) if meta else "no CSV ingested yet — call ingest_orders_csv",
        "orders": orders,
    }


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Full picture of one order: CSV line items (base truth) plus every
    related email update, and the current status inferred from the latest
    status email.

    Args:
        order_id: Amazon order number, e.g. 111-1234567-1234567.
    """
    order_id = order_id.strip()
    conn = _db()
    items = [dict(r) for r in conn.execute(
        "SELECT * FROM order_items WHERE order_id = ?", (order_id,)
    ).fetchall()]
    emails = [dict(r) for r in conn.execute(
        """SELECT e.date, e.kind, e.subject, e.snippet FROM email_updates e
           JOIN email_orders eo ON eo.message_id = e.message_id
           WHERE eo.order_id = ? ORDER BY e.date""",
        (order_id,),
    ).fetchall()]
    latest = _latest_status(conn, order_id)
    conn.close()
    if not items and not emails:
        return {"error": f"No CSV rows or emails known for {order_id}. "
                         "Try sync_gmail or check the order number."}
    total = sum(filter(None, (_num(i.get("total")) for i in items))) if items else None
    return {
        "order_id": order_id,
        "current_status": (latest or {}).get("kind")
                          or (items[0].get("shipment_status") or items[0].get("order_status") if items else None),
        "csv_items": items,
        "csv_total": total,
        "email_updates": emails,
    }


@mcp.tool()
def recent_updates(limit: int = 20) -> list:
    """Latest stored email updates across all orders (run sync_gmail first
    to refresh), joined with product names from the CSV when available.

    Args:
        limit: Max updates to return.
    """
    limit = max(1, min(int(limit), 100))
    conn = _db()
    rows = conn.execute(
        "SELECT date, kind, subject, order_ids, snippet FROM email_updates "
        "WHERE kind != 'other' ORDER BY date DESC LIMIT ?", (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        ids = json.loads(d.pop("order_ids") or "[]")
        d["order_ids"] = ids
        names = []
        for oid in ids:
            names += [x[0] for x in conn.execute(
                "SELECT product_name FROM order_items WHERE order_id=? LIMIT 3", (oid,)
            ).fetchall()]
        if names:
            d["products"] = names
        out.append(d)
    conn.close()
    return out


def main():
    mcp.run()


if __name__ == "__main__":
    main()
