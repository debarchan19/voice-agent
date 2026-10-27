"""The "Where Is My Order" agents: Greeter -> OrderStatus <-> Resolution.

Shared call context lives in UserData (session.userdata), so the caller never has
to repeat themselves after a hand-off. Every hand-off, tool call and userdata change
publishes a JSON message on the "wismo.state" topic, which drives the side panel
(active agent, activity log, notepad) in index.html.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from livekit import rtc
from livekit.agents import Agent, RunContext, ToolError, function_tool, llm
from tavily import AsyncTavilyClient

import db
import email_tool

logger = logging.getLogger("wismo")

STATE_TOPIC = "wismo.state"
GREETING = (
    "Hi, thanks for calling order support. I can check on a delivery for you. "
    "What's your order number, or the phone number on your account?"
)
MAX_VERIFY_ATTEMPTS = 3


@dataclass
class UserData:
    room: rtc.Room | None = None
    current_agent: str = "Greeter"
    order_id: str | None = None
    phone: str | None = None
    customer_id: int | None = None
    customer_name: str | None = None
    order_status: str | None = None
    promised_date: str | None = None
    verified: bool = False
    verify_attempts: int = 0
    issue_summary: str | None = None
    last_action: dict | None = None  # what Resolution just did; the email is built from this
    email_sent: bool = False

    def summary(self) -> str:
        parts = []
        if self.order_id:
            parts.append(f"order number {self.order_id}")
        if self.phone:
            parts.append(f"phone number {self.phone}")
        if self.verified:
            parts.append(f"caller verified as {self.customer_name}, order status {self.order_status}")
        else:
            parts.append("caller not verified yet")
        if self.issue_summary:
            parts.append(f"issue: {self.issue_summary}")
        return "; ".join(parts) + "."

    def notepad(self) -> dict:
        """The userdata the panel shows, with personal details hidden until verified."""
        return {
            "current_agent": self.current_agent,
            "order_id": self.order_id or "—",
            "verified": "yes" if self.verified else "no",
            "customer_name": self.customer_name if self.verified else "—",
            "issue_summary": self.issue_summary or "—",
            "last_action": _describe_action(self.last_action) if self.last_action else "—",
        }


RunCtx = RunContext[UserData]


async def _db(fn, *args, **kwargs):
    """Run a db.py function on a fresh connection in a worker thread."""

    def run():
        conn = db.connect()
        try:
            return fn(conn, *args, **kwargs)
        finally:
            conn.close()

    return await asyncio.to_thread(run)


def _short_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d:%a, %b} {d.day}"


def _long_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d:%A, %B} {d.day}"


def _describe_action(action: dict) -> str:
    kind = action["action"]
    if kind == "reschedule":
        return f"rescheduled to {_short_date(action['new_date'])}"
    return f"{kind} (ticket {action['ticket_id']})"


async def report(ud: UserData, log: str | None = None) -> None:
    """Publish the call state to the browser panel, plus an optional activity-log line."""
    if ud.room is None or not ud.room.isconnected():
        return
    # Order details only go to the screen once the caller is verified, same as the voice.
    payload = {
        "type": "state",
        "agent": ud.current_agent,
        "verified": ud.verified,
        "customer": ud.customer_name if ud.verified else None,
        "order_id": ud.order_id,
        "status": ud.order_status if ud.verified else None,
        "promised_date": ud.promised_date if ud.verified else None,
        "notepad": ud.notepad(),
        "log": log,
    }
    try:
        await ud.room.local_participant.publish_data(json.dumps(payload), topic=STATE_TOPIC)
    except Exception:
        logger.warning("failed to publish call state", exc_info=True)


def _require_verified(ud: UserData, order_id: str | None = None) -> str:
    if not ud.verified or not ud.order_id:
        raise ToolError(
            "The caller isn't verified yet. Ask for the last four digits of the phone "
            "number on the order and call verify_customer first."
        )
    if order_id and db.normalize_order_id(order_id) != ud.order_id:
        raise ToolError(f"Only the verified order, {ud.order_id}, can be discussed or changed.")
    return ud.order_id


def _speak_time(ts: str) -> str:
    t = datetime.fromisoformat(ts)
    return f"{db.speakable_date(ts)} at {t:%-I:%M %p}".replace(":00 ", " ")


def _speak_event(event: dict) -> str:
    where = "" if event["location"] == "Online" else f" in {event['location']}"
    return f"{event['description']}{where}, {_speak_time(event['timestamp'])}"


async def _describe_order(order: dict) -> str:
    """Order facts for the LLM, with dates already phrased for speech."""
    events = await _db(db.get_tracking_events, order["id"])
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
        facts.append(f"Latest update: {_speak_event(events[-1])}")
    facts.append(f"Tracking number, only read if the caller asks: {order['tracking_number']}")
    return ". ".join(facts) + "."


def voice_rules() -> str:
    today = date.today()
    return f"""You are part of a phone support line for an online shop, helping callers with late or missing packages.
Today is {today:%A, %B} {today.day}, {today.year} ({today.isoformat()}).

How you speak:
- Everything you say is read aloud. Use plain conversational sentences only: no lists, bullet points, markdown, emojis, or URLs.
- Keep each turn to two or three short sentences. The one exception is explaining an order's status, where you may use up to four.
- Be warm and natural, and use contractions.
- When you hear an order number or a full phone number, read it back in small chunks to confirm it, for example "that's O R D, 4 8 2 1 3, right?" Speech recognition can mishear numbers.
- The exception is the last four digits used for verification: never repeat those back. Call verify_customer straight away; if they're wrong it simply fails and you ask again.
- Never read a tracking number aloud unless the caller asks for it, and never digit by digit unless they ask.
- Say dates naturally, using the phrases the tools give you, like "this Thursday", rather than raw dates.
- If an order is late, apologise once, sincerely, then focus on what happens next. Don't keep apologising.
- Never share order details until verify_customer has succeeded.
- If the caller asks for a person, is very upset, or you can't help, use escalate_to_human.
- Don't mention tools, agents, or transfers. To the caller this is one continuous conversation."""


class SupportAgent(Agent):
    """Shared voice rules, hand-off context, panel updates and escalate_to_human."""

    display_name = "Support"
    role = ""

    def __init__(self, *, chat_ctx: llm.ChatContext | None = None, userdata: UserData | None = None) -> None:
        instructions = f"{voice_rules()}\n\n{self.role}"
        if userdata:
            instructions += f"\n\nContext from earlier in this call: {userdata.summary()}"
        super().__init__(instructions=instructions, chat_ctx=chat_ctx)

    def entry_prompt(self, ud: UserData) -> str:
        return ""

    async def on_enter(self) -> None:
        ud: UserData = self.session.userdata
        ud.current_agent = self.display_name
        await report(ud, f"Handed off to {self.display_name}")
        self.session.generate_reply(instructions=self.entry_prompt(ud))

    def handoff_ctx(self) -> llm.ChatContext:
        """The conversation so far, without tool calls, for the next agent."""
        return self.chat_ctx.copy(
            exclude_function_call=True,
            exclude_instructions=True,
            exclude_handoff=True,
            exclude_config_update=True,
        )

    @function_tool
    async def escalate_to_human(self, context: RunCtx, reason: str) -> str:
        """Create a support ticket and arrange for a human specialist to call the caller back.
        Use when the caller asks for a person, is very upset, or you can't solve the problem.

        Args:
            reason: One sentence on why the caller needs a human.
        """
        # Deliberately allowed for unverified callers, so someone who fails verification can still reach a person.
        ud = context.userdata
        order_id = ud.order_id if ud.verified else None
        notes = reason if ud.verified else f"{reason} (unverified caller, gave order {ud.order_id or 'none'})"
        ticket_id = await _db(db.create_ticket, order_id, "escalation", notes)
        if ud.verified:
            ud.last_action, ud.email_sent = {"action": "escalation", "ticket_id": ticket_id, "reason": reason}, False
        await report(ud, f"Escalated to a human, ticket {ticket_id}")
        return (
            f"Escalation ticket {ticket_id} created. Tell the caller a specialist will call them back "
            f"within one business day at the number on file, and give them ticket number {ticket_id}."
        )


class GreeterAgent(SupportAgent):
    display_name = "Greeter"
    role = """Your role: greet the caller and find out which order they're calling about.
Collect either their order number or the phone number on their account, read it back in chunks, and once they confirm it, call transfer_to_order_status.
If they ask a general question that isn't about a specific order, like a carrier's holiday schedule, you may use search_web and answer in one sentence."""

    async def on_enter(self) -> None:
        ud: UserData = self.session.userdata
        ud.current_agent = self.display_name
        await report(ud, "Call started")
        # Fixed wording, so the first line of every call is predictable.
        await self.session.say(GREETING)

    @function_tool
    async def transfer_to_order_status(
        self, context: RunCtx, order_id: str | None = None, phone: str | None = None
    ) -> Agent | str:
        """Hand the call to the order specialist once the caller has confirmed their order number or phone number.

        Args:
            order_id: The order number as heard, for example "ORD-48213" or "48213".
            phone: The phone number on the account, digits only.
        """
        ud = context.userdata
        if order_id:
            normalized = db.normalize_order_id(order_id)
            if normalized is None:
                return "That isn't a valid order number. Order numbers are O R D followed by five digits. Ask the caller to repeat it."
            ud.order_id = normalized
            await report(ud, f"Captured order {normalized}")
        elif phone:
            if len(db.digits_only(phone)) < 10:
                return "That phone number is too short. Ask for the full number including area code."
            ud.phone = db.digits_only(phone)[-10:]
            await report(ud, f"Captured phone ending {ud.phone[-4:]}")
        else:
            return "Ask the caller for their order number or the phone number on their account first."
        return OrderStatusAgent(chat_ctx=self.handoff_ctx(), userdata=ud)

    @function_tool
    async def search_web(self, context: RunCtx, query: str) -> str:
        """Search the web for a general question that isn't about a specific order, such as carrier holiday schedules or a major weather disruption. Never use it for order details.

        Args:
            query: A short search query.
        """
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise ToolError("Web search isn't available right now.")
        await report(context.userdata, f"Searched the web: {query}")
        result = await AsyncTavilyClient(api_key).search(
            query, max_results=3, include_answer=True, search_depth="basic", timeout=10
        )
        answer = result.get("answer") or " ".join(r["content"][:300] for r in result.get("results", []))
        if not answer:
            return "Nothing useful came back. Tell the caller you couldn't find that."
        return f"Search result. Summarise it in one spoken sentence with no URLs: {answer}"


class OrderStatusAgent(SupportAgent):
    display_name = "Order Status"
    role = """Your role: verify the caller, look up their order, and explain its status in plain spoken language.
Verification: ask for the last four digits of the phone number on the order. As soon as the caller says them, call verify_customer without reading them back. Don't share anything about the order before it succeeds.
Right after verifying, give the status in two sentences at most, then ask one short question about what they'd like to do.
If you only have a phone number, call lookup_orders_by_phone, tell the caller which order numbers you found, and confirm which one they mean.
When explaining a late order, use the delay reason and the latest tracking update. For more history, call get_tracking_events.
If the caller wants to reschedule, get a refund, report a problem, or speak to a person, call transfer_to_resolution."""

    def entry_prompt(self, ud: UserData) -> str:
        if ud.verified:
            return "Pick up where the conversation left off and ask if there's anything else about this order."
        if ud.order_id:
            return (
                f"First call lookup_order_by_id for {ud.order_id}. Then, in one sentence, ask for the "
                "last four digits of the phone number on the order to verify it's them."
            )
        return "First call lookup_orders_by_phone with the phone number the caller gave."

    @function_tool
    async def lookup_order_by_id(self, context: RunCtx, order_id: str) -> str:
        """Look up an order by its order number.

        Args:
            order_id: The order number, for example "ORD-48213".
        """
        ud = context.userdata
        normalized = db.normalize_order_id(order_id)
        order = await _db(db.get_order, normalized) if normalized else None
        if order is None:
            await report(ud, f"No order found for {order_id}")
            return "No order with that number. Read back what you heard in chunks and ask the caller to repeat it."
        if normalized != ud.order_id:
            ud.order_id, ud.verified, ud.verify_attempts = normalized, False, 0
        await report(ud, f"Looked up {normalized}")
        if not ud.verified:
            return f"Order {normalized} exists. Verify the caller with the last four digits of their phone number before sharing anything else."
        return await _describe_order(order)

    @function_tool
    async def lookup_orders_by_phone(self, context: RunCtx, phone: str) -> str:
        """Find the order numbers on the account with this phone number.

        Args:
            phone: The phone number, digits only.
        """
        ud = context.userdata
        orders = await _db(db.get_orders_by_phone, phone)
        await report(ud, f"Found {len(orders)} order{'s' if len(orders) != 1 else ''} for phone ending {db.digits_only(phone)[-4:]}")
        if not orders:
            return "No account with that phone number. Read it back in chunks and ask the caller to check it."
        listed = ", ".join(f"{o['id']} placed {db.speakable_date(o['order_date'])}" for o in orders[:3])
        more = f", plus {len(orders) - 3} older ones" if len(orders) > 3 else ""
        return f"Found {len(orders)} orders: {listed}{more}. Ask which one they're calling about, then verify them."

    @function_tool
    async def verify_customer(self, context: RunCtx, order_id: str, last_four_phone_digits: str) -> str:
        """Verify the caller owns the order using the last four digits of the phone number on the account.

        Args:
            order_id: The order number being discussed.
            last_four_phone_digits: The four digits the caller said.
        """
        ud = context.userdata
        normalized = db.normalize_order_id(order_id)
        if normalized is None:
            return "That order number isn't valid. Confirm it with the caller first."
        if ud.verify_attempts >= MAX_VERIFY_ATTEMPTS:
            return "Too many failed attempts. Don't try again; offer to escalate to a human instead."

        customer = await _db(db.verify_customer, normalized, last_four_phone_digits)
        if customer is None:
            ud.verify_attempts += 1
            left = MAX_VERIFY_ATTEMPTS - ud.verify_attempts
            await report(ud, f"Verification failed ({left} left)")
            return f"Those digits don't match. {left} attempt{'s' if left != 1 else ''} left. Ask them to try again."

        order = await _db(db.get_order, normalized)
        ud.order_id, ud.verified = normalized, True
        ud.customer_id, ud.customer_name = customer["id"], customer["name"]
        ud.order_status, ud.promised_date = order["status"], order["promised_date"]
        await report(ud, "Verification passed")
        first_name = customer["name"].split()[0]
        return f"Verified. The caller's first name is {first_name}; thank them by name. {await _describe_order(order)}"

    @function_tool
    async def get_tracking_events(self, context: RunCtx, order_id: str) -> str:
        """Get the recent tracking history for the verified order, to explain where it is or why it's late.

        Args:
            order_id: The verified order number.
        """
        ud = context.userdata
        oid = _require_verified(ud, order_id)
        events = await _db(db.get_tracking_events, oid)
        await report(ud, f"Fetched tracking history ({len(events)} events)")
        return " Then: ".join(f"{_speak_event(e)}." for e in events[-4:])

    @function_tool
    async def transfer_to_resolution(self, context: RunCtx, issue_summary: str) -> Agent:
        """Hand the call to the resolution specialist when the caller wants to reschedule, request a refund, report a problem, or speak to a person.

        Args:
            issue_summary: What the caller wants, in one sentence.
        """
        ud = context.userdata
        _require_verified(ud)
        ud.issue_summary = issue_summary
        return ResolutionAgent(chat_ctx=self.handoff_ctx(), userdata=ud)


class ResolutionAgent(SupportAgent):
    display_name = "Resolution"
    role = """Your role: fix the problem for a verified caller by rescheduling delivery, requesting a refund, opening a support ticket, or escalating to a human.
Before any action, say exactly what you're about to do, including the date or reason, and wait for a clear yes. Never act without that yes.
Turn relative dates like "Friday" into YYYY-MM-DD using today's date. Only future dates are allowed.
After an action succeeds, call send_confirmation_email straight away. Then tell the caller in one or two sentences that it's done and whether the confirmation email was sent, and ask if there's anything else.
If they have another question about the order's status, call transfer_back_to_order_status."""

    def entry_prompt(self, ud: UserData) -> str:
        return f"The caller wants this: {ud.issue_summary}. Acknowledge it briefly and ask the one question you need to proceed."

    async def _record(self, ud: UserData, action: dict, log: str) -> None:
        ud.last_action, ud.email_sent = action, False
        await report(ud, log)

    @function_tool
    async def reschedule_delivery(self, context: RunCtx, order_id: str, new_date: str) -> str:
        """Move the delivery to a new date. Only call after the caller explicitly said yes to the exact date.

        Args:
            order_id: The verified order number.
            new_date: The new delivery date as YYYY-MM-DD.
        """
        ud = context.userdata
        oid = _require_verified(ud, order_id)
        try:
            result = await _db(db.reschedule_delivery, oid, new_date)
        except ValueError as e:
            raise ToolError(str(e)) from None
        ud.promised_date = result["new_date"]
        action = {"action": "reschedule", "new_date": result["new_date"], "ticket_id": result["ticket_id"]}
        await self._record(ud, action, f"Rescheduled delivery to {_short_date(result['new_date'])}")
        return (
            f"Done. Delivery is now {db.speakable_date(result['new_date'])}. "
            f"Reference ticket {result['ticket_id']}. Now call send_confirmation_email."
        )

    @function_tool
    async def request_refund(self, context: RunCtx, order_id: str, reason: str) -> str:
        """Open a refund request. Only call after the caller explicitly said yes to requesting a refund.

        Args:
            order_id: The verified order number.
            reason: Why the caller wants a refund.
        """
        ud = context.userdata
        oid = _require_verified(ud, order_id)
        try:
            ticket_id = await _db(db.request_refund, oid, reason)
        except ValueError as e:
            raise ToolError(str(e)) from None
        await self._record(ud, {"action": "refund", "ticket_id": ticket_id, "reason": reason}, f"Refund requested, ticket {ticket_id}")
        return (
            f"Refund request {ticket_id} opened. Refunds go back to the original payment method "
            "within 5 to 7 business days. Now call send_confirmation_email."
        )

    @function_tool
    async def create_ticket(
        self,
        context: RunCtx,
        order_id: str,
        type: Literal["lost_package", "damaged", "other"],
        notes: str,
    ) -> str:
        """Open a support ticket for a problem that isn't a reschedule or refund. Only call after the caller agreed.

        Args:
            order_id: The verified order number.
            type: The kind of problem.
            notes: One or two sentences describing it.
        """
        ud = context.userdata
        oid = _require_verified(ud, order_id)
        ticket_id = await _db(db.create_ticket, oid, type, notes)
        await self._record(ud, {"action": "ticket", "ticket_id": ticket_id, "reason": notes}, f"Ticket {ticket_id} opened")
        return f"Ticket {ticket_id} opened. The team will follow up within one business day. Now call send_confirmation_email."

    @function_tool
    async def send_confirmation_email(self, context: RunCtx) -> str:
        """Email the caller a confirmation of the action that was just completed. Call right after a successful reschedule, refund request, ticket, or escalation."""
        ud = context.userdata
        oid = _require_verified(ud)
        if not ud.last_action:
            raise ToolError("There's no completed action to confirm yet.")
        if ud.email_sent:
            return "The confirmation email for this action was already sent. Don't send it again."

        customer = await _db(db.get_customer, ud.customer_id)
        order = await _db(db.get_order, oid)
        details = {"item": order["item_name"], "ticket_id": ud.last_action.get("ticket_id"),
                   "reason": ud.last_action.get("reason")}
        if ud.last_action.get("new_date"):
            details["new_date"] = _long_date(ud.last_action["new_date"])

        result = await email_tool.send_confirmation_email(
            customer["email"], oid, customer["name"], ud.last_action["action"], details
        )
        if not result["ok"]:
            await report(ud, "Email failed")
            return "The email failed to send. Tell the caller honestly that the confirmation email didn't go through, but their change is saved."
        ud.email_sent = True
        await report(ud, "Email sent")
        return "Confirmation email sent to the address on file. Tell the caller it's on its way."

    @function_tool
    async def transfer_back_to_order_status(self, context: RunCtx) -> Agent:
        """Hand back to the order specialist for more questions about the order's status or tracking."""
        return OrderStatusAgent(chat_ctx=self.handoff_ctx(), userdata=context.userdata)
