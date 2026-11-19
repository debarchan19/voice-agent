"""The tool schemas each agent's model is shown, per backend.

With no tuning (Claude, and the Qwen baseline) the model gets the tool objects themselves, exactly
as before. With `qwen_tool_docs` or `plain_optional_args` it gets rewritten OpenAI-format schemas
instead. Only the text the model reads changes: tool names and argument names are the same, the
graph's ToolNode still runs the real tools with their own validation, and the verification gate
is untouched.
"""

from __future__ import annotations

import copy

from langchain_core.utils.function_calling import convert_to_openai_tool

from .state import AgentName
from .tools import TOOLS
from .tuning import Tuning

ORDER_ID = "Order number, like ORD-12345."
VERIFIED_ORDER = "The verified order number, like ORD-12345."

# B2: shorter descriptions, one line per argument, exact allowed values. Not written from any test scenario.
QWEN_TOOL_DOCS: dict[str, tuple[str, dict[str, str]]] = {
    "transfer_to_order_status": (
        "Pass the call to the order specialist once the caller has confirmed the order number or phone number "
        "you read back. Send exactly one of order_id or phone; leave the other out.",
        {"order_id": ORDER_ID, "phone": "The full phone number on the account, 10 digits, digits only."},
    ),
    "search_web": (
        "Search the web for a general question that is not about one order, such as a carrier's holiday "
        "schedule. Never use it for order details.",
        {"query": "A short search query."},
    ),
    "escalate_to_human": (
        "Open a ticket so a human specialist calls the caller back. Use it when the caller asks for a person, "
        "is very upset, or you can't help.",
        {"reason": "One sentence: why the caller needs a person."},
    ),
    "lookup_order_by_id": ("Look up an order by its order number.", {"order_id": ORDER_ID}),
    "lookup_orders_by_phone": (
        "List the order numbers on the account with this phone number.",
        {"phone": "The full phone number, digits only."},
    ),
    "verify_customer": (
        "Check that the caller owns the order. Call it as soon as the caller says the last four digits of "
        "their phone number.",
        {"order_id": "The order number being discussed, like ORD-12345.",
         "last_four_phone_digits": "Exactly the four digits the caller said, like 0123."},
    ),
    "get_tracking_events": ("Get the tracking history of the verified order.", {"order_id": VERIFIED_ORDER}),
    "transfer_to_resolution": (
        "Pass the call to the resolution specialist when the verified caller wants to reschedule, get a refund, "
        "report a lost or damaged package, or speak to a person.",
        {"issue_summary": "One sentence: what the caller wants."},
    ),
    "reschedule_delivery": (
        "Move the delivery to a new date. Call it only after the caller said yes to that exact date.",
        {"order_id": VERIFIED_ORDER, "new_date": "The new date as YYYY-MM-DD. Must be in the future."},
    ),
    "request_refund": (
        "Request a refund. Call it only after the caller said yes to a refund.",
        {"order_id": VERIFIED_ORDER, "reason": "One sentence: why the caller wants a refund."},
    ),
    "create_ticket": (
        "Open a support ticket for a problem that isn't a reschedule or a refund. Call it only after the "
        "caller said yes.",
        {"order_id": VERIFIED_ORDER,
         "type": "One of: lost_package (shows delivered but never arrived), damaged (arrived broken), other.",
         "notes": "One or two sentences describing the problem."},
    ),
    "transfer_back_to_order_status": (
        "Pass the call back to the order specialist for more questions about the order's status or tracking.",
        {},
    ),
}


def _plain_optional(params: dict) -> None:
    """B3: `anyOf: [string, null], default: null` becomes a plain string that simply isn't required."""
    required = set(params.get("required") or [])
    for name, prop in params.get("properties", {}).items():
        options = prop.get("anyOf")
        if name in required or not options:
            continue
        kinds = [o for o in options if o.get("type") != "null"]
        if len(kinds) == 1 and len(kinds) < len(options):
            prop.pop("anyOf")
            prop.pop("default", None)
            prop.update(kinds[0])
            prop["description"] = ("Optional; leave it out if you don't have it. " + prop.get("description", "")).strip()


def tool_specs(agent: AgentName, tuning: Tuning) -> list:
    """What to pass to `bind_tools` for this agent: the tools themselves, or rewritten schemas."""
    tools = TOOLS[agent]
    if not (tuning.has("qwen_tool_docs") or tuning.has("plain_optional_args")):
        return tools
    specs = []
    for t in tools:
        spec = copy.deepcopy(convert_to_openai_tool(t))
        fn, params = spec["function"], spec["function"].setdefault("parameters", {"type": "object", "properties": {}})
        if tuning.has("qwen_tool_docs"):
            desc, args = QWEN_TOOL_DOCS[t.name]
            fn["description"] = desc
            for name, text in args.items():
                params["properties"][name]["description"] = text
        if tuning.has("plain_optional_args"):
            _plain_optional(params)
        specs.append(spec)
    return specs
