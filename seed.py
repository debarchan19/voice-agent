"""Create shop.db and fill it with fake customers, orders and tracking history.

Customers and orders are listed explicitly below, so the README test table always
matches. Dates are relative to the day you run it, so "delayed" and "out for delivery"
always look current. Re-running drops and rebuilds the database.

All names, phone numbers (fictional 555-01xx range) and emails (@example.com) are fake.

Usage: python seed.py
"""

import os
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import db

CUSTOMERS = [
    ("Maya Patel", "720-555-0142"),
    ("James Carter", "312-555-0187"),
    ("Sofia Ramirez", "415-555-0123"),
    ("Daniel Kim", "617-555-0168"),
    ("Aisha Johnson", "206-555-0119"),
    ("Lucas Moreau", "503-555-0156"),
    ("Priya Nair", "917-555-0131"),
    ("Ethan Brooks", "805-555-0174"),
    ("Hannah Weber", "720-555-0109"),
    ("Omar Haddad", "312-555-0195"),
]

CARRIER_PREFIX = {"Swift Parcel": "SP", "NorthStar Freight": "NS", "Metro Express": "MX", "BlueRoute Logistics": "BR"}

DELAY_REASONS = {
    "weather": (
        "A winter storm put the Denver hub on a weather hold for two days",
        "Weather hold: hub operations paused due to winter storm",
    ),
    "backlog": (
        "The carrier has a backlog at its regional sort facility after a holiday surge",
        "Carrier backlog: package held at sort facility",
    ),
    "address": (
        "The driver couldn't deliver because the apartment number is missing from the address",
        "Delivery attempt failed: address incomplete, apartment number missing",
    ),
}


@dataclass
class OrderSpec:
    id: str
    customer: int  # index into CUSTOMERS
    item: str
    status: str
    carrier: str
    warehouse: str
    hub: str
    city: str
    ordered_days_ago: int
    promised_offset: int  # days from today
    delay: str | None = None
    label: str = ""


ORDERS = [
    OrderSpec("ORD-48213", 0, "Stainless steel espresso machine", "delayed", "Metro Express",
              "Reno, NV", "Denver, CO", "Boulder, CO", 8, -2, delay="weather", label="delayed (weather hold)"),
    OrderSpec("ORD-51907", 1, "Noise-cancelling headphones", "delayed", "Swift Parcel",
              "Columbus, OH", "Indianapolis, IN", "Chicago, IL", 7, -1, delay="backlog", label="delayed (carrier backlog)"),
    OrderSpec("ORD-36458", 2, "Ergonomic office chair", "delayed", "BlueRoute Logistics",
              "Dallas, TX", "Ontario, CA", "San Diego, CA", 9, -3, delay="address", label="delayed (address issue)"),
    OrderSpec("ORD-72041", 3, "Robot vacuum cleaner", "out_for_delivery", "NorthStar Freight",
              "Allentown, PA", "Louisville, KY", "Boston, MA", 4, 0),
    OrderSpec("ORD-19376", 0, "Cast iron skillet set", "delivered", "Swift Parcel",
              "Reno, NV", "Denver, CO", "Boulder, CO", 21, -16),
    OrderSpec("ORD-60582", 4, "Trail running shoes", "delivered", "Metro Express",
              "Reno, NV", "Ontario, CA", "Seattle, WA", 12, -7),
    OrderSpec("ORD-27719", 5, "Adjustable standing desk", "cancelled", "BlueRoute Logistics",
              "Dallas, TX", "Memphis, TN", "Portland, OR", 10, -4),
    OrderSpec("ORD-83350", 6, "Insulated winter parka", "returned", "NorthStar Freight",
              "Allentown, PA", "Louisville, KY", "Brooklyn, NY", 30, -24),
    OrderSpec("ORD-44926", 7, "Mechanical keyboard", "processing", "Swift Parcel",
              "Columbus, OH", "Memphis, TN", "Austin, TX", 1, 5),
    OrderSpec("ORD-95063", 8, "Digital air fryer", "shipped", "Metro Express",
              "Dallas, TX", "Denver, CO", "Phoenix, AZ", 3, 2),
]


def _timeline(start: date, end: date, steps: list[tuple[str, str]], now: datetime) -> list[tuple]:
    """Spread events evenly from 8am on start to 6pm on end, never later than now."""
    t0 = datetime.combine(start, time(8, 0))
    t1 = min(datetime.combine(end, time(18, 0)), now)
    t1 = max(t1, t0 + timedelta(hours=len(steps)))
    gap = (t1 - t0) / max(len(steps) - 1, 1)
    return [
        ((t0 + gap * i).replace(second=0, microsecond=0).isoformat(timespec="minutes"), loc, desc)
        for i, (loc, desc) in enumerate(steps)
    ]


def _events(o: OrderSpec, order_date: date, promised: date, today: date, now: datetime) -> list[tuple]:
    """3 to 6 tracking events that match the order's status."""
    placed = ("Online", "Order placed")
    shipped = (o.warehouse, "Shipped from warehouse")
    at_hub = (o.hub, "Arrived at carrier sort facility")
    left_hub = (o.hub, "Departed sort facility, in transit")
    local = (o.city, "Arrived at local delivery station")
    out = (o.city, "Out for delivery")

    if o.status == "processing":
        steps, end = [placed, ("Online", "Payment confirmed"), (o.warehouse, "Order is being prepared at the warehouse")], today
    elif o.status == "shipped":
        steps, end = [placed, shipped, at_hub, left_hub], today
    elif o.status == "out_for_delivery":
        steps, end = [placed, shipped, at_hub, local, out], today
    elif o.status == "delivered":
        steps, end = [placed, shipped, at_hub, local, out, (o.city, "Delivered, left at front door")], promised
    elif o.status == "delayed":
        exception = DELAY_REASONS[o.delay][1]
        where = o.city if o.delay == "address" else o.hub
        steps = [placed, shipped, at_hub, (where, exception)]
        if o.delay == "address":
            steps.insert(3, out)
        end = today
    elif o.status == "cancelled":
        steps = [placed, ("Online", "Payment confirmed"), ("Online", "Order cancelled at customer request, refund issued")]
        end = order_date + timedelta(days=1)
    else:  # returned
        steps = [placed, shipped, out, (o.city, "Delivered"), (o.city, "Return started by customer"),
                 (o.warehouse, "Return received at warehouse, refund issued")]
        end = today - timedelta(days=3)
    return _timeline(order_date, end, steps, now)


def seed(path: str | None = None, today: date | None = None) -> list[dict]:
    """Rebuild the database at path. Returns every order with its test details."""
    path = path or db.DB_PATH
    today = today or date.today()
    now = datetime.now() if today == date.today() else datetime.combine(today, time(18, 0))
    rng = random.Random(42)  # only for tracking numbers, so they stay the same too

    if os.path.exists(path):
        os.remove(path)
    conn = db.connect(path)
    db.create_schema(conn)

    for i, (name, phone) in enumerate(CUSTOMERS, start=1):
        email = f"{name.split()[0].lower()}@example.com"
        conn.execute("INSERT INTO customers VALUES (?, ?, ?, ?)", (i, name, phone, email))

    result = []
    for o in ORDERS:
        order_date = today - timedelta(days=o.ordered_days_ago)
        promised = today + timedelta(days=o.promised_offset)
        tracking = CARRIER_PREFIX[o.carrier] + "".join(str(rng.randint(0, 9)) for _ in range(12))
        delay_reason = DELAY_REASONS[o.delay][0] if o.delay else None
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (o.id, o.customer + 1, o.item, order_date.isoformat(), promised.isoformat(),
             o.status, o.carrier, tracking, delay_reason),
        )
        conn.executemany(
            "INSERT INTO tracking_events (order_id, timestamp, location, description) VALUES (?, ?, ?, ?)",
            [(o.id, *e) for e in _events(o, order_date, promised, today, now)],
        )
        name, phone = CUSTOMERS[o.customer]
        result.append({"id": o.id, "status": o.status, "label": o.label or o.status.replace("_", " "),
                       "item": o.item, "customer": {"name": name, "phone": phone}})

    # One existing ticket so the table isn't empty. Ticket numbers start at 1001.
    conn.execute(
        "INSERT INTO support_tickets (id, order_id, type, notes, created_at, status) VALUES (1001, ?, 'lost_package', ?, ?, 'open')",
        ("ORD-51907", "Customer asked where the package is", (now - timedelta(days=1)).isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return result


if __name__ == "__main__":
    orders = seed()
    print(f"Seeded {db.DB_PATH}: {len(CUSTOMERS)} customers, {len(orders)} orders.\n")
    print(f"{'Order ID':<11} {'Status':<26} {'Customer':<15} {'Last 4':<7} Full phone")
    for o in orders:
        c = o["customer"]
        print(f"{o['id']:<11} {o['label']:<26} {c['name']:<15} {c['phone'][-4:]:<7} {c['phone']}")
