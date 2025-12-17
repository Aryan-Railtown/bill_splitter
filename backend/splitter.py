import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

import railtracks as rt
from railtracks import agent_node
from pydantic import BaseModel, Field

from backend.bill_parser import SpliterOutput
from backend.tools.data_tools import (
    from_cents,
    to_cents,
    tool_add_transaction_custom_split,
    tool_get_group_balances,
    tool_init_store,
)

STORE_CURRENCY_FALLBACK = "CAD"


class BalanceSummary(BaseModel):
    balances: Dict[str, float] = Field(
        description=(
            "Mapping of member display name to their net balance in dollars "
            "(positive => others owe them, negative => they owe the group)."
        )
    )


init_store_tool = rt.function_node(tool_init_store)
add_custom_tx_tool = rt.function_node(tool_add_transaction_custom_split)
get_group_balances_tool = rt.function_node(tool_get_group_balances)


system_message = """
You are the Data Manager for a bill-splitting application. You manage a JSON ledger
using the provided tools. Always obey the following rules:

1. Use `init_store` before any other tool call to guarantee the store exists.
2. You are given the exact per-user share amounts (in cents); use them verbatim when
   calling `add_transaction_custom_split`. Do not recompute or change those numbers.
3. Always record exactly one custom-split transaction per bill. Include each item's
   metadata in the `items` argument so future audits are possible.
4. After inserting the transaction, call `get_group_balances` to retrieve the net edges.
5. Respond with a JSON object that matches the BalanceSummary schema
   (member display names mapped to net dollar amounts with two decimals).
"""

llm_model = rt.llm.OpenAILLM("gpt-4o")

finance_agent = rt.agent_node(
    name="Data Manager",
    system_message=system_message,
    llm=llm_model,
    output_schema=BalanceSummary,
    tool_nodes=[init_store_tool, add_custom_tx_tool, get_group_balances_tool],
)


async def process(
    store_path: str,
    group_id: str,
    members: List[Dict[str, Any]],
    parsed_bill: SpliterOutput,
    item_assignments: Dict[str, List[str]],
    paid_by: str,
    currency: str | None = None,
    bill_title: str | None = None,
    notes: str = "",
) -> Dict[str, float]:
    """
    Ingests an itemized bill, drives the LLM orchestrator to persist the transaction,
    and returns the updated per-member balances for the group.

    Args:
        store_path: Filesystem path where the JSON ledger is stored.
        group_id: Identifier of the group in the ledger.
        members: List of dicts with at least {"id": str, "name": str}.
        parsed_bill: Output from the parser agent (items + costs).
        item_assignments: Mapping of item name to the member names or ids who consumed it.
        paid_by: Member name or id of the payer.
        currency: Optional ISO currency override (defaults to store fallback).
        bill_title: Optional title for the transaction (defaults to timestamped label).
        notes: Optional note persisted with the transaction.

    Returns:
        Dict[str, float]: Mapping of member name to net balance in dollars.
    """
    tool_init_store(store_path)

    if not members:
        raise ValueError("members list must be non-empty")

    member_by_id = {m["id"]: m for m in members}
    member_id_by_name = {m["name"]: m["id"] for m in members}

    def resolve_member(identifier: str) -> str:
        if identifier in member_by_id:
            return identifier
        if identifier in member_id_by_name:
            return member_id_by_name[identifier]
        raise ValueError(f"Unknown member identifier: {identifier}")

    paid_by_id = resolve_member(paid_by)
    paid_by_name = member_by_id[paid_by_id]["name"]

    currency = currency or STORE_CURRENCY_FALLBACK
    bill_title = bill_title or f"Imported bill {datetime.now(timezone.utc).date().isoformat()}"

    shares_by_user_cents: Dict[str, int] = defaultdict(int)
    bill_items_payload: List[Dict[str, Any]] = []
    total_cents = 0

    for item in parsed_bill.items:
        raw_assignees = item_assignments.get(item.item) or item_assignments.get(item.item.strip(), [])
        if isinstance(raw_assignees, str):
            raw_assignees = [raw_assignees]

        if raw_assignees:
            assigned_ids = [resolve_member(r) for r in raw_assignees]
        else:
            assigned_ids = [m["id"] for m in members]

        # Preserve caller order but deduplicate
        seen = set()
        assigned_ids = [uid for uid in assigned_ids if not (uid in seen or seen.add(uid))]

        cost_cents = to_cents(item.cost)
        total_cents += cost_cents
        num_participants = len(assigned_ids)
        if num_participants == 0:
            raise ValueError(f"Item '{item.item}' has no valid assignees")

        base = cost_cents // num_participants
        remainder = cost_cents % num_participants
        for idx, user_id in enumerate(assigned_ids):
            share = base + (1 if idx < remainder else 0)
            shares_by_user_cents[user_id] += share

        bill_items_payload.append(
            {
                "name": item.item,
                "cost_cents": cost_cents,
                "assigned_member_ids": assigned_ids,
                "assigned_member_names": [member_by_id[uid]["name"] for uid in assigned_ids],
            }
        )

    if paid_by_id not in shares_by_user_cents:
        shares_by_user_cents[paid_by_id] = 0

    shares_payload = [
        {
            "user_id": uid,
            "user_name": member_by_id[uid]["name"],
            "share_amount_cents": cents,
            "share_amount_dollars": float(Decimal(cents) / Decimal(100)),
        }
        for uid, cents in shares_by_user_cents.items()
    ]

    orchestration_prompt = f"""
You are processing a single bill for group '{group_id}' stored at '{store_path}'.

Bill metadata:
- Title: {bill_title}
- Total amount cents: {total_cents}
- Currency: {currency}
- Paid by: {paid_by_id} ({paid_by_name})
- Notes: {notes}

Members:
{json.dumps(members, indent=2)}

Per-item assignments (costs already converted to cents):
{json.dumps(bill_items_payload, indent=2)}

Exact per-user shares (must be used verbatim when calling add_transaction_custom_split):
{json.dumps(shares_payload, indent=2)}

Actions to perform:
1. Call `init_store` with path="{store_path}".
2. Call `add_transaction_custom_split` with:
   - path = "{store_path}"
   - group_id = "{group_id}"
   - title = "{bill_title}"
   - paid_by = "{paid_by_id}"
   - currency = "{currency}"
   - notes = {json.dumps(notes)}
   - items = {json.dumps(bill_items_payload)}
   - shares = the list shown above (use share_amount_cents values as-is).
3. After the transaction is recorded, call `get_group_balances` for this group.
4. Build your final reply using the BalanceSummary schema. Map member *names* to their net balances.
   Positive numbers mean the member is owed money; negative numbers mean they owe the group.
"""

    resp = await rt.call(
        finance_agent,
        user_input=rt.llm.UserMessage(orchestration_prompt),
    )

    # Pull the structured reply (already validated against BalanceSummary)
    summary: BalanceSummary = resp.structured  # type: ignore
    computed_balances = dict(summary.balances)

    # Recompute from the ledger for determinism (guards against hallucinated math in the reply)
    balances_snapshot = tool_get_group_balances(store_path, group_id)
    balance_by_user_cents: Dict[str, int] = {m["id"]: 0 for m in members}
    for edge in balances_snapshot.get("edges", []):
        amount_cents = int(edge["amount_cents"])
        balance_by_user_cents[edge["from_user_id"]] -= amount_cents
        balance_by_user_cents[edge["to_user_id"]] += amount_cents

    verified_balances: Dict[str, float] = {}
    for member in members:
        cents = balance_by_user_cents.get(member["id"], 0)
        dollars = float((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))
        verified_balances[member["name"]] = dollars

    # Optional: surface both (e.g. log a warning if they diverge)
    if any(abs(verified_balances[k] - computed_balances.get(k, 0.0)) > 0.009 for k in verified_balances):
        print("Warning: LLM-reported balances differ from ledger; using ledger values.")

    return verified_balances