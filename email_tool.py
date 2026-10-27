"""Confirmation emails over Gmail SMTP.

Sending runs in a worker thread so it never blocks the conversation, and it never
raises: callers get {"ok": bool, ...} so the agent can say honestly whether it worked.
Set DEMO_RECIPIENT_EMAIL to send every email to one test inbox instead of the customer.
"""

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage
from html import escape

logger = logging.getLogger("wismo.email")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT = 15
SIGN_OFF = "ShopEasy Support (demo)"

SUBJECTS = {
    "reschedule": "delivery rescheduled",
    "refund": "refund requested",
    "ticket": "support ticket opened",
    "escalation": "a specialist will call you back",
}


def recipient_for(customer_email: str) -> str:
    return os.environ.get("DEMO_RECIPIENT_EMAIL", "").strip() or customer_email


def build_confirmation_email(
    to: str, order_id: str, customer_name: str, action: str, details: dict, sender: str = ""
) -> EmailMessage:
    """Build the email. details may hold new_date (spoken form), ticket_id, reason, item."""
    first_name = customer_name.split()[0]
    lines = {
        "reschedule": f"we've moved the delivery of your order to {details.get('new_date')}.",
        "refund": "we've opened a refund request for your order. Refunds go back to your original payment method within 5 to 7 business days.",
        "ticket": "we've opened a support ticket for your order, and the team will follow up within one business day.",
        "escalation": "we've passed your case to a specialist, who will call you back within one business day.",
    }
    summary = lines.get(action, "we've updated your order.")

    facts = [("Order", order_id)]
    if details.get("item"):
        facts.append(("Item", details["item"]))
    if details.get("new_date"):
        facts.append(("New delivery date", details["new_date"]))
    if details.get("reason"):
        facts.append(("Reason", details["reason"]))
    if details.get("ticket_id"):
        facts.append(("Reference", f"Ticket {details['ticket_id']}"))

    msg = EmailMessage()
    msg["Subject"] = f"Your order {order_id}: {SUBJECTS.get(action, 'update')}"
    msg["From"] = f"{SIGN_OFF} <{sender}>" if sender else SIGN_OFF
    msg["To"] = to

    text_facts = "\n".join(f"{k}: {v}" for k, v in facts)
    msg.set_content(
        f"Hi {first_name},\n\nThanks for calling. As we discussed, {summary}\n\n{text_facts}\n\n"
        f"If anything looks wrong, just reply to this email.\n\nThanks,\n{SIGN_OFF}\n\n"
        "This is a demo message with fake order data."
    )

    rows = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#6b7280">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#111827;font-weight:600">{escape(str(v))}</td></tr>'
        for k, v in facts
    )
    msg.add_alternative(
        f"""<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#111827">
  <p style="font-size:16px">Hi {escape(first_name)},</p>
  <p style="font-size:16px;line-height:1.5">Thanks for calling. As we discussed, {escape(summary)}</p>
  <table style="border-collapse:collapse;font-size:14px;margin:16px 0">{rows}</table>
  <p style="font-size:14px;color:#374151">If anything looks wrong, just reply to this email.</p>
  <p style="font-size:14px;color:#374151">Thanks,<br><strong>{escape(SIGN_OFF)}</strong></p>
  <p style="font-size:12px;color:#9ca3af;margin-top:24px">This is a demo message with fake order data.</p>
</div>""",
        subtype="html",
    )
    return msg


def _send(msg: EmailMessage, address: str, password: str) -> None:
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as smtp:
        smtp.login(address, password)
        smtp.send_message(msg)


async def send_confirmation_email(
    customer_email: str, order_id: str, customer_name: str, action: str, details: dict
) -> dict:
    address = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not address or not password:
        logger.error("GMAIL_ADDRESS or GMAIL_APP_PASSWORD is not set")
        return {"ok": False, "error": "email isn't configured"}

    to = recipient_for(customer_email)
    msg = build_confirmation_email(to, order_id, customer_name, action, details, sender=address)
    try:
        await asyncio.to_thread(_send, msg, address, password)
    except Exception as e:
        logger.exception("failed to send confirmation email for %s", order_id)
        return {"ok": False, "error": type(e).__name__}
    logger.info("sent confirmation email for %s to %s", order_id, to)
    return {"ok": True, "to": to}
