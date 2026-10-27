import asyncio
import smtplib
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402
import email_tool  # noqa: E402
import seed  # noqa: E402

TODAY = date(2026, 10, 26)  # a Monday

DELAYED_WEATHER = "ORD-48213"  # Maya Patel, 0142
DELAYED_BACKLOG = "ORD-51907"  # James Carter, 0187
DELAYED_ADDRESS = "ORD-36458"  # Sofia Ramirez, 0123
DELIVERED = "ORD-60582"
CANCELLED = "ORD-27719"
SHIPPED = "ORD-95063"


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "shop.db")
    seed.seed(path, today=TODAY)
    c = db.connect(path)
    yield c
    c.close()


# --- Seed ----------------------------------------------------------------------


def test_seed_matches_spec(conn):
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 10
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM orders GROUP BY status").fetchall())
    assert counts == {
        "delayed": 3, "out_for_delivery": 1, "delivered": 2, "cancelled": 1,
        "returned": 1, "processing": 1, "shipped": 1,
    }
    reasons = [r[0] for r in conn.execute("SELECT delay_reason FROM orders WHERE status = 'delayed'")]
    assert len(set(reasons)) == 3 and all(reasons)
    per_order = [r[0] for r in conn.execute("SELECT COUNT(*) FROM tracking_events GROUP BY order_id")]
    assert len(per_order) == 10 and all(3 <= n <= 6 for n in per_order)
    emails = [r[0] for r in conn.execute("SELECT email FROM customers")]
    assert all(e.endswith("@example.com") for e in emails)


def test_seed_dates_are_relative_to_today(tmp_path):
    later = TODAY + timedelta(days=30)
    seed.seed(str(tmp_path / "later.db"), today=later)
    c = db.connect(str(tmp_path / "later.db"))
    assert db.get_order(c, "ORD-72041")["promised_date"] == later.isoformat()  # out for delivery today
    assert db.get_order(c, DELAYED_WEATHER)["promised_date"] < later.isoformat()  # delayed: promised date passed
    c.close()


# --- Lookups and verification --------------------------------------------------


@pytest.mark.parametrize(
    "spoken, expected",
    [("ORD-48213", "ORD-48213"), ("o r d 4 8 2 1 3", "ORD-48213"), ("48213", "ORD-48213"), ("4821", None), ("", None)],
)
def test_normalize_order_id(spoken, expected):
    assert db.normalize_order_id(spoken) == expected


def test_lookup_order_by_id(conn):
    order = db.get_order(conn, DELAYED_WEATHER)
    assert order["status"] == "delayed"
    assert order["customer_name"] == "Maya Patel"
    assert "weather hold" in order["delay_reason"]
    assert db.get_order(conn, "ORD-00000") is None


def test_lookup_orders_by_phone(conn):
    found = {o["id"] for o in db.get_orders_by_phone(conn, "+1 (720) 555-0142")}
    assert found == {DELAYED_WEATHER, "ORD-19376"}
    assert db.get_orders_by_phone(conn, "000-000-0000") == []
    assert db.get_orders_by_phone(conn, "123") == []


def test_verify_customer(conn):
    assert db.verify_customer(conn, DELAYED_BACKLOG, "0187")["name"] == "James Carter"
    assert db.verify_customer(conn, DELAYED_BACKLOG, "0 1 8 7")["name"] == "James Carter"
    assert db.verify_customer(conn, DELAYED_BACKLOG, "0142") is None  # someone else's digits
    assert db.verify_customer(conn, DELAYED_BACKLOG, "18") is None
    assert db.verify_customer(conn, "ORD-00000", "0187") is None


def test_tracking_events_are_in_order(conn):
    for (order_id,) in conn.execute("SELECT id FROM orders").fetchall():
        timestamps = [e["timestamp"] for e in db.get_tracking_events(conn, order_id)]
        assert timestamps == sorted(timestamps)
    last = db.get_tracking_events(conn, DELAYED_ADDRESS)[-1]
    assert "address" in last["description"].lower()


# --- Actions -------------------------------------------------------------------


def test_reschedule_delivery(conn):
    new_date = (TODAY + timedelta(days=4)).isoformat()
    result = db.reschedule_delivery(conn, DELAYED_WEATHER, new_date, today=TODAY)
    assert result["new_date"] == new_date
    assert db.get_order(conn, DELAYED_WEATHER)["promised_date"] == new_date
    ticket = conn.execute("SELECT type, order_id FROM support_tickets WHERE id = ?", (result["ticket_id"],)).fetchone()
    assert tuple(ticket) == ("reschedule", DELAYED_WEATHER)


@pytest.mark.parametrize(
    "order_id, new_date, message",
    [
        (DELIVERED, (TODAY + timedelta(days=3)).isoformat(), "delivered"),
        (SHIPPED, (TODAY - timedelta(days=1)).isoformat(), "future"),
        (SHIPPED, TODAY.isoformat(), "future"),
        (SHIPPED, "next friday", "YYYY-MM-DD"),
    ],
)
def test_reschedule_rejections(conn, order_id, new_date, message):
    with pytest.raises(ValueError, match=message):
        db.reschedule_delivery(conn, order_id, new_date, today=TODAY)


def test_request_refund(conn):
    ticket_id = db.request_refund(conn, DELAYED_ADDRESS, "Too late for the move")
    row = conn.execute("SELECT type, status, notes FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
    assert tuple(row) == ("refund", "open", "Too late for the move")
    with pytest.raises(ValueError, match="cancelled"):
        db.request_refund(conn, CANCELLED, "changed my mind")


def test_create_ticket(conn):
    first = db.create_ticket(conn, SHIPPED, "damaged", "Box arrived crushed")
    second = db.create_ticket(conn, None, "escalation", "Caller wants a supervisor")
    assert first > 1001 and second > first
    with pytest.raises(ValueError):
        db.create_ticket(conn, None, "not-a-type", "")


@pytest.mark.parametrize(
    "offset, expected",
    [
        (0, "today"), (1, "tomorrow"), (-1, "yesterday"), (3, "this Thursday"),
        (7, "Monday, November 2"), (-3, "last Friday, October 23"), (30, "Wednesday, November 25"),
    ],
)
def test_speakable_date(offset, expected):
    assert db.speakable_date((TODAY + timedelta(days=offset)).isoformat(), today=TODAY) == expected


# --- Verification gate in the graph tools --------------------------------------


@pytest.fixture
def tools_env(tmp_path, monkeypatch):
    """The real tools pointed at a fresh seeded DB, run through a real ToolNode."""
    path = str(tmp_path / "shop.db")
    seed.seed(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    from fakes import invoke_tool

    return invoke_tool, path


def run_tool(env, name, args, state=None):
    invoke_tool, _ = env
    return asyncio.run(invoke_tool(name, args, state))


def test_resolution_tools_refuse_unverified_callers(tools_env):
    _, path = tools_env
    future = (date.today() + timedelta(days=3)).isoformat()
    unverified = {"order_id": DELAYED_WEATHER, "verified": False}
    calls = [
        ("reschedule_delivery", {"order_id": DELAYED_WEATHER, "new_date": future}),
        ("request_refund", {"order_id": DELAYED_WEATHER, "reason": "late"}),
        ("create_ticket", {"order_id": DELAYED_WEATHER, "type": "other", "notes": "note"}),
        ("get_tracking_events", {"order_id": DELAYED_WEATHER}),
        ("transfer_to_resolution", {"issue_summary": "wants a refund"}),
    ]
    for name, args in calls:
        message, state = run_tool(tools_env, name, args, unverified)
        assert message.status == "error" and "isn't verified" in message.content, name
        assert state.get("active_agent") != "resolution" and not state.get("last_action"), name

    c = db.connect(path)
    assert db.get_order(c, DELAYED_WEATHER)["promised_date"] < date.today().isoformat()  # unchanged
    assert c.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0] == 1  # only the seeded one
    c.close()


def test_lookup_hides_details_until_verified(tools_env):
    state = {"order_id": DELAYED_WEATHER}
    message, after = run_tool(tools_env, "lookup_order_by_id", {"order_id": DELAYED_WEATHER}, state)
    assert "espresso" not in message.content.lower() and "verify" in message.content.lower()

    failed, after = run_tool(
        tools_env, "verify_customer", {"order_id": DELAYED_WEATHER, "last_four_phone_digits": "9999"}, state
    )
    assert "don't match" in failed.content and not after.get("verified") and after["verify_attempts"] == 1

    passed, after = run_tool(
        tools_env, "verify_customer", {"order_id": DELAYED_WEATHER, "last_four_phone_digits": "0142"}, state
    )
    assert after["verified"] and after["customer_name"] == "Maya Patel" and "espresso" in passed.content.lower()


def test_verified_caller_can_reschedule_and_other_orders_stay_locked(tools_env):
    verified = {"order_id": DELAYED_WEATHER, "verified": True, "customer_id": 1, "customer_name": "Maya Patel"}
    future = (date.today() + timedelta(days=3)).isoformat()

    message, _ = run_tool(tools_env, "reschedule_delivery", {"order_id": "ORD-19376", "new_date": future}, verified)
    assert message.status == "error" and "Only the verified order" in message.content  # Maya's other order

    message, after = run_tool(tools_env, "reschedule_delivery", {"order_id": DELAYED_WEATHER, "new_date": future}, verified)
    assert "Done" in message.content
    assert after["last_action"]["action"] == "reschedule" and after["promised_date"] == future
    assert after["email_pending"] is True


def test_escalation_is_allowed_for_unverified_callers(tools_env):
    message, after = run_tool(
        tools_env, "escalate_to_human", {"reason": "wants a person"}, {"order_id": DELAYED_WEATHER, "verified": False}
    )
    assert "Escalation ticket" in message.content
    assert not after.get("last_action")  # nothing attached to the order, and no email owed
    c = db.connect(tools_env[1])
    row = c.execute("SELECT order_id, notes FROM support_tickets WHERE type = 'escalation'").fetchone()
    assert row["order_id"] is None and "unverified caller" in row["notes"]
    c.close()


def test_verification_attempts_are_capped(tools_env):
    state = {"order_id": DELAYED_WEATHER, "verify_attempts": 3}
    message, after = run_tool(
        tools_env, "verify_customer", {"order_id": DELAYED_WEATHER, "last_four_phone_digits": "0142"}, state
    )
    assert "Too many failed attempts" in message.content and not after.get("verified")


# --- Email ---------------------------------------------------------------------


def test_build_confirmation_email():
    msg = email_tool.build_confirmation_email(
        "maya@example.com", DELAYED_WEATHER, "Maya Patel", "reschedule",
        {"new_date": "Friday, October 30", "ticket_id": 1002, "item": "Stainless steel espresso machine"},
        sender="shop@gmail.com",
    )
    assert msg["Subject"] == f"Your order {DELAYED_WEATHER}: delivery rescheduled"
    assert msg["To"] == "maya@example.com"
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    for body in (text, html):
        assert "Hi Maya" in body
        assert "Friday, October 30" in body
        assert "Ticket 1002" in body
        assert "ShopEasy Support (demo)" in body


def test_recipient_override(monkeypatch):
    monkeypatch.delenv("DEMO_RECIPIENT_EMAIL", raising=False)
    assert email_tool.recipient_for("maya@example.com") == "maya@example.com"
    monkeypatch.setenv("DEMO_RECIPIENT_EMAIL", "inbox@test.dev")
    assert email_tool.recipient_for("maya@example.com") == "inbox@test.dev"


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.sent, self.login_args = host, port, [], None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture
def gmail_env(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "shop@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("DEMO_RECIPIENT_EMAIL", "inbox@test.dev")
    FakeSMTP.instances = []


def test_send_email_success(monkeypatch, gmail_env):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    result = asyncio.run(email_tool.send_confirmation_email(
        "maya@example.com", DELAYED_WEATHER, "Maya Patel", "refund", {"ticket_id": 1003}))
    assert result == {"ok": True, "to": "inbox@test.dev"}
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 465)
    assert smtp.login_args == ("shop@gmail.com", "abcdefghijklmnop")  # spaces stripped
    assert smtp.sent[0]["To"] == "inbox@test.dev"


def test_send_email_failure_is_reported_not_raised(monkeypatch, gmail_env):
    class BrokenSMTP(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP_SSL", BrokenSMTP)
    result = asyncio.run(email_tool.send_confirmation_email(
        "maya@example.com", DELAYED_WEATHER, "Maya Patel", "refund", {"ticket_id": 1003}))
    assert result == {"ok": False, "error": "SMTPAuthenticationError"}


def test_send_email_without_credentials(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    result = asyncio.run(email_tool.send_confirmation_email(
        "maya@example.com", DELAYED_WEATHER, "Maya Patel", "refund", {}))
    assert result["ok"] is False
