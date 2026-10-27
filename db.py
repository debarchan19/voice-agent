"""SQLite schema and query functions for the fake shop.

Everything here is plain synchronous sqlite3 so it can be tested without LiveKit.
The voice agents call these through asyncio.to_thread.
"""

import os
import re
import sqlite3
from datetime import date, datetime

DB_PATH = os.environ.get("SHOP_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop.db"))

STATUSES = (
    "processing",
    "shipped",
    "out_for_delivery",
    "delivered",
    "delayed",
    "cancelled",
    "returned",
)
CLOSED_STATUSES = {"delivered", "cancelled", "returned"}
TICKET_TYPES = {"reschedule", "refund", "escalation", "lost_package", "damaged", "other"}

SCHEMA = f"""
CREATE TABLE customers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    phone   TEXT NOT NULL UNIQUE,
    email   TEXT NOT NULL
);

CREATE TABLE orders (
    id              TEXT PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    item_name       TEXT NOT NULL,
    order_date      TEXT NOT NULL,
    promised_date   TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ({", ".join(f"'{s}'" for s in STATUSES)})),
    carrier         TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    delay_reason    TEXT
);

CREATE TABLE tracking_events (
    id          INTEGER PRIMARY KEY,
    order_id    TEXT NOT NULL REFERENCES orders(id),
    timestamp   TEXT NOT NULL,
    location    TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE support_tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT REFERENCES orders(id),
    type        TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_events_order ON tracking_events(order_id, timestamp);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --- Normalisation helpers ---------------------------------------------------


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def normalize_order_id(text: str) -> str | None:
    """Turn spoken or partial input ("o r d 4 8 2 1 3", "48213") into ORD-48213."""
    digits = digits_only(text)
    return f"ORD-{digits}" if len(digits) == 5 else None


def speakable_date(iso: str, today: date | None = None) -> str:
    """Phrase a date the way a person would say it on the phone."""
    today = today or date.today()
    d = date.fromisoformat(iso[:10])
    delta = (d - today).days
    weekday = f"{d:%A}"
    full = f"{weekday}, {d:%B} {d.day}"

    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    same_week = d.isocalendar()[:2] == today.isocalendar()[:2]
    if 2 <= delta <= 6:
        return f"this {weekday}" if same_week else f"next {full}"
    if -6 <= delta <= -2:
        return f"this past {weekday}" if same_week else f"last {full}"
    return full


# --- Queries -----------------------------------------------------------------


def get_order(conn: sqlite3.Connection, order_id: str) -> dict | None:
    row = conn.execute(
        """SELECT o.*, c.name AS customer_name
           FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    return dict(row) if row else None


def get_customer(conn: sqlite3.Connection, customer_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return dict(row) if row else None


def get_orders_by_phone(conn: sqlite3.Connection, phone: str) -> list[dict]:
    digits = digits_only(phone)[-10:]
    if len(digits) != 10:
        return []
    rows = conn.execute(
        """SELECT o.id, o.status, o.order_date, o.customer_id
           FROM orders o JOIN customers c ON c.id = o.customer_id
           WHERE REPLACE(c.phone, '-', '') = ?
           ORDER BY o.order_date DESC""",
        (digits,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_tracking_events(conn: sqlite3.Connection, order_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT timestamp, location, description FROM tracking_events
           WHERE order_id = ? ORDER BY timestamp""",
        (order_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def verify_customer(conn: sqlite3.Connection, order_id: str, last_four: str) -> dict | None:
    """Return the customer if last_four matches the phone on the order, else None."""
    last_four = digits_only(last_four)
    if len(last_four) != 4:
        return None
    row = conn.execute(
        """SELECT c.id, c.name, c.phone FROM orders o
           JOIN customers c ON c.id = o.customer_id WHERE o.id = ?""",
        (order_id,),
    ).fetchone()
    if row is None or digits_only(row["phone"])[-4:] != last_four:
        return None
    return {"id": row["id"], "name": row["name"]}


# --- Actions -----------------------------------------------------------------


def create_ticket(
    conn: sqlite3.Connection, order_id: str | None, type: str, notes: str = ""
) -> int:
    if type not in TICKET_TYPES:
        raise ValueError(f"Unknown ticket type {type!r}")
    cur = conn.execute(
        "INSERT INTO support_tickets (order_id, type, created_at, status, notes) VALUES (?, ?, ?, 'open', ?)",
        (order_id, type, datetime.now().isoformat(timespec="seconds"), notes),
    )
    conn.commit()
    return cur.lastrowid


def reschedule_delivery(
    conn: sqlite3.Connection, order_id: str, new_date: str, today: date | None = None
) -> dict:
    order = get_order(conn, order_id)
    if order is None:
        raise ValueError("Order not found")
    if order["status"] in CLOSED_STATUSES:
        raise ValueError(f"Can't reschedule an order that is {order['status']}")
    try:
        new = date.fromisoformat(new_date)
    except ValueError:
        raise ValueError("new_date must be YYYY-MM-DD") from None
    if new <= (today or date.today()):
        raise ValueError("The new delivery date must be in the future")

    conn.execute("UPDATE orders SET promised_date = ? WHERE id = ?", (new.isoformat(), order_id))
    ticket_id = create_ticket(
        conn, order_id, "reschedule", f"Moved from {order['promised_date']} to {new.isoformat()}"
    )
    return {"order_id": order_id, "new_date": new.isoformat(), "ticket_id": ticket_id}


def request_refund(conn: sqlite3.Connection, order_id: str, reason: str) -> int:
    order = get_order(conn, order_id)
    if order is None:
        raise ValueError("Order not found")
    if order["status"] == "cancelled":
        raise ValueError("This order was cancelled, so it has already been refunded")
    return create_ticket(conn, order_id, "refund", reason)
