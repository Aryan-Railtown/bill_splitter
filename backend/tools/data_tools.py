from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import railtracks as rt

DEFAULT_STORE = {
    "schema_version": 1,
    "app": {"currency_default": "CAD"},
    "users": [],
    "groups": [],
    "transactions": [],
    "payments": [],
    "balances": {
        "updated_at": None,
        # store as adjacency maps for fast updates:
        # balances["by_group"][group_id]["net"][from_user_id][to_user_id] = amount_cents
        "by_group": {},
        "global": {"net": {}},
    },
}

def now_iso() -> str:
    """Return the current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()

def new_id(prefix: str) -> str:
    """Return a short random identifier prefixed with the supplied string (e.g. `u_...`)."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def to_cents(amount: Any) -> int:
    """
    Convert a numeric value (dollars) to integer cents, rounding half-up to 2 decimal places.
    
    Args:
        amount: String, float, Decimal, or int representing the amount. Int is assumed to
            already be in cents.
    """
    if isinstance(amount, int):
        return amount
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)

def from_cents(cents: int) -> float:
    """Convert integer cents into a float dollar amount."""
    return float(Decimal(cents) / 100)


# -----------------------------
# Atomic file IO
# -----------------------------
def read_json(path: Path) -> Dict[str, Any]:
    """Load the store from `path`; if missing, return a deep copy of DEFAULT_STORE."""
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_STORE))
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Persist JSON to `path` safely by writing to a temp file and renaming atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX


# -----------------------------
# Lookup helpers
# -----------------------------
def index_by_id(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Return a dict keyed by `item["id"]` for fast lookups."""
    return {x["id"]: x for x in items}

def find_user_id_by_name(store: Dict[str, Any], name: str) -> Optional[str]:
    """Return the user id for the first user whose `name` matches exactly; None if not found."""
    for u in store["users"]:
        if u["name"] == name:
            return u["id"]
    return None

def require_user(store: Dict[str, Any], user_id: str) -> None:
    """Raise ValueError if `user_id` does not exist in `store["users"]`."""
    if user_id not in index_by_id(store["users"]):
        raise ValueError(f"Unknown user_id: {user_id}")

def require_group(store: Dict[str, Any], group_id: str) -> None:
    """Raise ValueError if `group_id` does not exist in `store["groups"]`."""
    if group_id not in index_by_id(store["groups"]):
        raise ValueError(f"Unknown group_id: {group_id}")


# -----------------------------
# Balance netting
# -----------------------------
def _get_net_map(root: Dict[str, Any], scope: str, group_id: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """
    Return the adjacency map (`net[from][to] = amount_cents`) for the given scope.

    Args:
        root: balances root object (e.g. store["balances"]).
        scope: "global" for cross-group netting or "by_group" for per-group netting.
        group_id: Required when scope = "by_group".
    """
    if scope == "global":
        root.setdefault("global", {}).setdefault("net", {})
        return root["global"]["net"]

    assert group_id is not None
    root.setdefault("by_group", {}).setdefault(group_id, {}).setdefault("net", {})
    return root["by_group"][group_id]["net"]

def _get_edge(net: Dict[str, Dict[str, int]], a: str, b: str) -> int:
    """Return the amount (in cents) recorded from `a` to `b` in the adjacency map."""
    return int(net.get(a, {}).get(b, 0))

def _set_edge(net: Dict[str, Dict[str, int]], a: str, b: str, value: int) -> None:
    """Set or delete the edge `a -> b` in the adjacency map, removing empty nodes."""
    if value <= 0:
        if a in net and b in net[a]:
            del net[a][b]
            if not net[a]:
                del net[a]
        return
    net.setdefault(a, {})[b] = int(value)

def apply_net_delta(net: Dict[str, Dict[str, int]], from_id: str, to_id: str, delta_cents: int) -> None:
    """
    Add `delta_cents` to the directed edge from `from_id` to `to_id`.

    The helper automatically cancels out opposite-direction edges (so you never end up with both
    A→B and B→A simultaneously). Negative amounts flip direction transparently.
    """
    if from_id == to_id or delta_cents == 0:
        return
    if delta_cents < 0:
        apply_net_delta(net, to_id, from_id, -delta_cents)
        return

    cur = _get_edge(net, from_id, to_id)
    _set_edge(net, from_id, to_id, cur + delta_cents)

    fwd = _get_edge(net, from_id, to_id)
    rev = _get_edge(net, to_id, from_id)
    cancel = min(fwd, rev)
    if cancel > 0:
        _set_edge(net, from_id, to_id, fwd - cancel)
        _set_edge(net, to_id, from_id, rev - cancel)


def update_balances_for_debt(store: Dict[str, Any], group_id: str, from_id: str, to_id: str, amount_cents: int) -> None:
    """
    Apply a single debt delta to both the per-group and global balance graphs.

    Args:
        store: The entire data store object.
        group_id: Group context in which the debt occurred.
        from_id: Debtor user id.
        to_id: Creditor user id.
        amount_cents: Positive value increases debt from `from_id` to `to_id`,
            negative value decreases it (e.g. from a payment).
    """
    net_g = _get_net_map(store["balances"], "by_group", group_id)
    apply_net_delta(net_g, from_id, to_id, amount_cents)
    net_global = _get_net_map(store["balances"], "global")
    apply_net_delta(net_global, from_id, to_id, amount_cents)
    store["balances"]["updated_at"] = now_iso()


# -----------------------------
# Public "tool" functions
# -----------------------------
def tool_add_transaction_custom_split(
    path: str,
    group_id: str,
    title: str,
    paid_by: str,
    shares: List[Dict[str, Any]],
    currency: Optional[str] = None,
    created_at: Optional[str] = None,
    notes: str = "",
    items: Optional[List[Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Record a bill in which each participant can have an arbitrary share.

    Args:
        path: Filesystem path to the JSON store.
        group_id: Group identifier.
        title: Human-friendly label for the bill.
        paid_by: User id of the payer.
        shares: List of dicts describing each participant’s share. Each entry must include:
            - "user_id": str
            - one of {"share_amount", "share_amount_cents"}:
                * share_amount (float/str/Decimal) is interpreted as dollars
                * share_amount_cents (int) is interpreted as cents
        currency: Optional ISO currency code (defaults to store["app"]["currency_default"]).
        created_at: Optional ISO8601 timestamp (default now).
        notes: Optional freeform string.
        items: Optional list of per-item metadata. Each dict can contain:
            - "name" or "item": item label (required)
            - "cost" (dollars) or "cost_cents" (int cents) (required)
            - "assigned_member_ids": list of user ids who consumed the item (optional)
            - any extra fields you wish to persist
        metadata: Optional dict that will be stored alongside the transaction for audit/debug.

    Returns:
        {
            "ok": True,
            "transaction_id": "<id>",
            "debts_created": [...],
            "total_amount_cents": int
        }

    Raises:
        ValueError: If the group/payer/users do not exist, shares are invalid, or total would be zero.
    """
    p = Path(path)
    store = read_json(p)

    require_group(store, group_id)
    require_user(store, paid_by)

    participants = index_by_id(store["users"])
    share_entries: List[Dict[str, Any]] = []
    total_cents = 0

    for entry in shares:
        user_id = entry.get("user_id")
        if not user_id:
            raise ValueError("Each share entry must include a user_id")
        if user_id not in participants:
            raise ValueError(f"Unknown user_id in shares: {user_id}")

        if "share_amount_cents" in entry:
            cents = int(entry["share_amount_cents"])
        elif "share_amount" in entry:
            cents = to_cents(entry["share_amount"])
        else:
            raise ValueError("Each share entry must include share_amount or share_amount_cents")

        if cents < 0:
            raise ValueError("share_amount_cents must be >= 0")

        share_entries.append({"user_id": user_id, "share_amount_cents": cents})
        total_cents += cents

    if total_cents <= 0:
        raise ValueError("Total share amount must be greater than zero")

    # Ensure payer appears in the split (even if their share is zero)
    payer_entry = next((s for s in share_entries if s["user_id"] == paid_by), None)
    if payer_entry is None:
        share_entries.append({"user_id": paid_by, "share_amount_cents": 0})

    participant_ids = [s["user_id"] for s in share_entries]

    normalized_items: List[Dict[str, Any]] = []
    if items:
        for raw in items:
            name = raw.get("name") or raw.get("item")
            if not name:
                raise ValueError("Each item metadata must include a 'name' or 'item' field")
            if "cost_cents" in raw:
                cost_cents = int(raw["cost_cents"])
            elif "cost" in raw:
                cost_cents = to_cents(raw["cost"])
            else:
                raise ValueError(f"Item '{name}' must include 'cost' or 'cost_cents'")

            assigned_ids = raw.get("assigned_member_ids", [])
            for uid in assigned_ids:
                require_user(store, uid)

            normalized_items.append(
                {
                    "name": name,
                    "cost_cents": cost_cents,
                    "assigned_member_ids": assigned_ids,
                    **{
                        k: v
                        for k, v in raw.items()
                        if k
                        not in {"name", "item", "cost", "cost_cents", "assigned_member_ids"}
                    },
                }
            )

    debts = []
    for s in share_entries:
        if s["user_id"] == paid_by:
            continue
        amt = s["share_amount_cents"]
        if amt > 0:
            debts.append(
                {"from_user_id": s["user_id"], "to_user_id": paid_by, "amount_cents": amt}
            )

    tx_id = new_id("t")
    tx = {
        "id": tx_id,
        "group_id": group_id,
        "title": title,
        "created_at": created_at or now_iso(),
        "currency": currency or store["app"].get("currency_default", "USD"),
        "total_amount_cents": total_cents,
        "paid_by": paid_by,
        "split": {
            "method": "custom",
            "participant_ids": participant_ids,
            "shares": share_entries,
        },
        "debts": debts,
        "notes": notes,
    }

    if normalized_items:
        tx["items"] = normalized_items
    if metadata:
        tx["metadata"] = metadata

    store["transactions"].append(tx)

    for d in debts:
        update_balances_for_debt(
            store,
            group_id=group_id,
            from_id=d["from_user_id"],
            to_id=d["to_user_id"],
            amount_cents=d["amount_cents"],
        )

    write_json_atomic(p, store)
    return {
        "ok": True,
        "transaction_id": tx_id,
        "debts_created": debts,
        "total_amount_cents": total_cents,
    }


def tool_init_store(path: str) -> Dict[str, Any]:
    """
    Initialize the JSON store file if it does not exist.

    Args:
        path: Absolute or relative filesystem path to the JSON store.

    Returns:
        {"ok": True, "path": "<resolved_path>"}
    """
    p = Path(path)
    if not p.exists():
        write_json_atomic(p, json.loads(json.dumps(DEFAULT_STORE)))
    return {"ok": True, "path": str(p)}

def tool_upsert_user(path: str, name: str) -> Dict[str, Any]:
    """
    Create a new user or return the existing one that matches `name`.

    Args:
        path: Filesystem path to the JSON store.
        name: Friendly display name for the user.

    Returns:
        {
            "ok": True,
            "user_id": "<user_id>",
            "created": bool   # True if a new record was inserted.
        }
    """
    p = Path(path)
    store = read_json(p)

    existing = find_user_id_by_name(store, name)
    if existing:
        return {"ok": True, "user_id": existing, "created": False}

    user_id = new_id("u")
    store["users"].append({"id": user_id, "name": name})
    write_json_atomic(p, store)
    return {"ok": True, "user_id": user_id, "created": True}

def tool_create_group(path: str, name: str, member_ids: List[str]) -> Dict[str, Any]:
    """
    Create a group with a predefined set of members.

    Args:
        path: Filesystem path to the JSON store.
        name: Display name for the group (e.g. "Roommates").
        member_ids: List of user ids; all users must already exist.

    Returns:
        {"ok": True, "group_id": "<group_id>"}

    Raises:
        ValueError: If any user id is unknown.
    """
    p = Path(path)
    store = read_json(p)

    for uid in member_ids:
        require_user(store, uid)

    group_id = new_id("g")
    store["groups"].append({"id": group_id, "name": name, "member_ids": member_ids})
    store["balances"]["by_group"].setdefault(group_id, {"net": {}})
    store["balances"]["updated_at"] = now_iso()

    write_json_atomic(p, store)
    return {"ok": True, "group_id": group_id}

def tool_add_transaction_equal_split(
    path: str,
    group_id: str,
    title: str,
    total_amount: Any,
    paid_by: str,
    participant_ids: List[str],
    currency: Optional[str] = None,
    created_at: Optional[str] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Record a bill inside a group and split it equally among participants.

    Balances are updated so each non-payer owes the payer their share. The payer never owes
    themselves (no zero-value debt edge written).

    Args:
        path: Filesystem path to the store.
        group_id: Group containing all participants.
        title: Human readable label (shown in UI).
        total_amount: Bill total in dollars (str/float/Decimal) or cents (int).
        paid_by: User id of the payer; must be in `participant_ids`.
        participant_ids: All participants who should share equally in the total.
        currency: Optional 3-letter currency code; defaults to store["app"]["currency_default"].
        created_at: Optional ISO8601 timestamp; default is current UTC time.
        notes: Optional freeform string (e.g. metadata from parser).

    Returns:
        {
            "ok": True,
            "transaction_id": "<id>",
            "debts_created": [
                {"from_user_id": "...", "to_user_id": "...", "amount_cents": int},
                ...
            ]
        }

    Raises:
        ValueError: If the group or users do not exist, payer is not in participants,
                    participant list is empty, or other validation fails.
    """
    p = Path(path)
    store = read_json(p)

    require_group(store, group_id)
    require_user(store, paid_by)
    if paid_by not in participant_ids:
        raise ValueError("paid_by must be in participant_ids")

    for uid in participant_ids:
        require_user(store, uid)

    total_cents = to_cents(total_amount)
    n = len(participant_ids)
    if n <= 0:
        raise ValueError("participant_ids must be non-empty")

    base = total_cents // n
    rem = total_cents % n
    shares: Dict[str, int] = {}
    for i, uid in enumerate(participant_ids):
        shares[uid] = base + (1 if i < rem else 0)

    debts = []
    for uid in participant_ids:
        if uid == paid_by:
            continue
        amt = shares[uid]
        if amt > 0:
            debts.append({"from_user_id": uid, "to_user_id": paid_by, "amount_cents": amt})

    tx_id = new_id("t")
    tx = {
        "id": tx_id,
        "group_id": group_id,
        "title": title,
        "created_at": created_at or now_iso(),
        "currency": currency or store["app"].get("currency_default", "USD"),
        "total_amount_cents": total_cents,
        "paid_by": paid_by,
        "split": {
            "method": "equal",
            "participant_ids": participant_ids,
            "shares": [{"user_id": uid, "share_amount_cents": shares[uid]} for uid in participant_ids],
        },
        "debts": debts,
        "notes": notes,
    }
    store["transactions"].append(tx)

    for d in debts:
        update_balances_for_debt(
            store,
            group_id=group_id,
            from_id=d["from_user_id"],
            to_id=d["to_user_id"],
            amount_cents=d["amount_cents"],
        )

    write_json_atomic(p, store)
    return {"ok": True, "transaction_id": tx_id, "debts_created": debts}

def tool_add_payment(
    path: str,
    group_id: str,
    from_user_id: str,
    to_user_id: str,
    amount: Any,
    currency: Optional[str] = None,
    created_at: Optional[str] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Record a direct payment from one group member to another and update balances.

    Args:
        path: Filesystem path to the store.
        group_id: Group in which the payment should be applied.
        from_user_id: Debtor paying down their balance.
        to_user_id: Creditor receiving the payment.
        amount: Payment amount in dollars (str/float/Decimal) or cents (int).
        currency: Optional ISO currency; defaults to store["app"]["currency_default"].
        created_at: Optional ISO8601 timestamp; default is current UTC time.
        notes: Optional freeform note.

    Returns:
        {"ok": True, "payment_id": "<id>"}

    Raises:
        ValueError: If group/users are unknown or payment amount <= 0.
    """
    p = Path(path)
    store = read_json(p)

    require_group(store, group_id)
    require_user(store, from_user_id)
    require_user(store, to_user_id)

    amount_cents = to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("Payment amount must be > 0")

    pay_id = new_id("p")
    payment = {
        "id": pay_id,
        "group_id": group_id,
        "created_at": created_at or now_iso(),
        "currency": currency or store["app"].get("currency_default", "USD"),
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "amount_cents": amount_cents,
        "notes": notes,
    }
    store["payments"].append(payment)

    update_balances_for_debt(store, group_id, from_user_id, to_user_id, -amount_cents)

    write_json_atomic(p, store)
    return {"ok": True, "payment_id": pay_id}

def tool_get_group_balances(path: str, group_id: str) -> Dict[str, Any]:
    """
    Fetch the current net debt edges for a given group (who owes whom how much).

    Args:
        path: Filesystem path to the store.
        group_id: Group id to inspect.

    Returns:
        {
            "ok": True,
            "group_id": "<group_id>",
            "edges": [
                {"from_user_id": "...", "to_user_id": "...", "amount_cents": int},
                ...
            ],
            "updated_at": "<ISO timestamp or None>"
        }

    Raises:
        ValueError: If the group is unknown.
    """
    p = Path(path)
    store = read_json(p)
    require_group(store, group_id)

    net = store["balances"]["by_group"].get(group_id, {}).get("net", {})
    edges = []
    for f, tos in net.items():
        for t, cents in tos.items():
            edges.append({"from_user_id": f, "to_user_id": t, "amount_cents": cents})

    return {"ok": True, "group_id": group_id, "edges": edges, "updated_at": store["balances"].get("updated_at")}

def tool_rebuild_balances(path: str) -> Dict[str, Any]:
    """
    Recompute all balances from scratch by replaying transactions and payments.

    Use this when you need to guarantee consistency (e.g. after manual edits).

    Args:
        path: Filesystem path to the JSON store.

    Returns:
        {"ok": True, "updated_at": "<ISO timestamp>"}
    """
    p = Path(path)
    store = read_json(p)

    store["balances"] = {"updated_at": None, "by_group": {}, "global": {"net": {}}}

    for tx in store.get("transactions", []):
        gid = tx["group_id"]
        store["balances"]["by_group"].setdefault(gid, {"net": {}})
        for d in tx.get("debts", []):
            update_balances_for_debt(store, gid, d["from_user_id"], d["to_user_id"], int(d["amount_cents"]))

    for pay in store.get("payments", []):
        gid = pay["group_id"]
        store["balances"]["by_group"].setdefault(gid, {"net": {}})
        update_balances_for_debt(store, gid, pay["from_user_id"], pay["to_user_id"], -int(pay["amount_cents"]))

    store["balances"]["updated_at"] = now_iso()
    write_json_atomic(p, store)
    return {"ok": True, "updated_at": store["balances"]["updated_at"]}