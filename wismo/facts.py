"""Helpers that turn database rows into text the model can say out loud."""

import asyncio
from datetime import date, datetime

import db


async def run_db(fn, *args, **kwargs):
    """Run a db.py function on a fresh connection in a worker thread."""

    def run():
        conn = db.connect()
        try:
            return fn(conn, *args, **kwargs)
        finally:
            conn.close()

    return await asyncio.to_thread(run)


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d:%a, %b} {d.day}"


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d:%A, %B} {d.day}"


def describe_action(action: dict) -> str:
    kind = action["action"]
    if kind == "reschedule":
        return f"rescheduled to {short_date(action['new_date'])}"
    return f"{kind} (ticket {action['ticket_id']})"


def speak_time(ts: str) -> str:
    t = datetime.fromisoformat(ts)
    return f"{db.speakable_date(ts)} at {t:%-I:%M %p}".replace(":00 ", " ")


def speak_event(event: dict) -> str:
    where = "" if event["location"] == "Online" else f" in {event['location']}"
    return f"{event['description']}{where}, {speak_time(event['timestamp'])}"


async def describe_order(order: dict) -> str:
    """Order facts for the LLM, with dates already phrased for speech."""
    events = await run_db(db.get_tracking_events, order["id"])
    facts = [
        f"Item: {order['item_name']}",
        f"Status: {order['status'].replace('_', ' ')}",
        f"Ordered: {db.speakable_date(order['order_date'])}",
        f"Promised delivery: {db.speakable_date(order['promised_date'])}",
        f"Carrier: {order['carrier']}",
    ]
    if order["delay_reason"]:
        facts.append(f"Delay reason: {order['delay_reason']}")
    if events:
        facts.append(f"Latest update: {speak_event(events[-1])}")
    facts.append(f"Tracking number, only read if the caller asks: {order['tracking_number']}")
    return ". ".join(facts) + "."
