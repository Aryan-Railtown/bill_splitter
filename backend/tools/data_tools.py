from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    return datetime.now(timezone.utc).isoformat()

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def to_cents(amount: Any) -> int:
    """
    Convert amount (str/float/Decimal/int) to integer cents, rounding half up to 2 dp.
    """
    if isinstance(amount, int):
        # assume already cents only if you pass it intentionally; otherwise treat as dollars?
        # safest: require str/float/Decimal for dollars; int for cents.
        return amount
    d = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(d * 100)

def from_cents(cents: int) -> float:
    return float(Decimal(cents) / 100)


# -----------------------------
# Atomic file IO
# -----------------------------
def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_STORE))
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)  # atomic on POSIX

# (Optional) If you worry about concurrent writes, add a simple lockfile strategy later.


# -----------------------------
# Lookup helpers
# -----------------------------
def index_by_id(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {x["id"]: x for x in items}

def find_user_id_by_name(store: Dict[str, Any], name: str) -> Optional[str]:
    for u in store["users"]:
        if u["name"] == name:
            return u["id"]
    return None

def require_user(store: Dict[str, Any], user_id: str) -> None:
    if user_id not in index_by_id(store["users"]):
        raise ValueError(f"Unknown user_id: {user_id}")

def require_group(store: Dict[str, Any], group_id: str) -> None:
    if group_id not in index_by_id(store["groups"]):
        raise ValueError(f"Unknown group_id: {group_id}")


# -----------------------------
# Balance netting
# -----------------------------
def _get_net_map(root: Dict[str, Any], scope: str, group_id: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """
    scope: "global" or "by_group"
    returns net[from][to] = cents
    """
    if scope == "global":
        root.setdefault("global", {}).setdefault("net", {})
        return root["global"]["net"]

    assert group_id is not None
    root.setdefault("by_group", {}).setdefault(group_id, {}).setdefault("net", {})
    return root["by_group"][group_id]["net"]

def _get_edge(net: Dict[str, Dict[str, int]], a: str, b: str) -> int:
    return int(net.get(a, {}).get(b, 0))

def _set_edge(net: Dict[str, Dict[str, int]], a: str, b: str, value: int) -> None:
    if value <= 0:
        if a in net and b in net[a]:
            del net[a][b]
            if not net[a]:
                del net[a]
        return
    net.setdefault(a, {})[b] = int(value)

def apply_net_delta(net: Dict[str, Dict[str, int]], from_id: str, to_id: str, delta_cents: int) -> None:
    """
    Add delta to from->to, then cancel opposite direction if present.
    Keeps net clean (no simultaneous A->B and B->A).
    """
    if from_id == to_id or delta_cents == 0:
        return
    if delta_cents < 0:
        # allow negative by flipping direction
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
    # group scope
    net_g = _get_net_map(store["balances"], "by_group", group_id)
    apply_net_delta(net_g, from_id, to_id, amount_cents)
    # global scope
    net_global = _get_net_map(store["balances"], "global")
    apply_net_delta(net_global, from_id, to_id, amount_cents)
    store["balances"]["updated_at"] = now_iso()


# -----------------------------
# Public "tool" functions
# -----------------------------
def tool_init_store(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        write_json_atomic(p, json.loads(json.dumps(DEFAULT_STORE)))
    return {"ok": True, "path": str(p)}

def tool_upsert_user(path: str, name: str) -> Dict[str, Any]:
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
    p = Path(path)
    store = read_json(p)

    for uid in member_ids:
        require_user(store, uid)

    group_id = new_id("g")
    store["groups"].append({"id": group_id, "name": name, "member_ids": member_ids})
    # ensure balances container exists
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

    # Equal split with remainder distribution (pennies) to first participants deterministically
    base = total_cents // n
    rem = total_cents % n
    shares: Dict[str, int] = {}
    for i, uid in enumerate(participant_ids):
        shares[uid] = base + (1 if i < rem else 0)

    # Debts: each non-payer owes payer their share
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

    # Incrementally update balances
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

    # Payment reduces what from_user owes to to_user => apply negative debt
    update_balances_for_debt(store, group_id, from_user_id, to_user_id, -amount_cents)

    write_json_atomic(p, store)
    return {"ok": True, "payment_id": pay_id}

def tool_get_group_balances(path: str, group_id: str) -> Dict[str, Any]:
    p = Path(path)
    store = read_json(p)
    require_group(store, group_id)

    net = store["balances"]["by_group"].get(group_id, {}).get("net", {})
    # Convert adjacency map to edges list for UI
    edges = []
    for f, tos in net.items():
        for t, cents in tos.items():
            edges.append({"from_user_id": f, "to_user_id": t, "amount_cents": cents})

    return {"ok": True, "group_id": group_id, "edges": edges, "updated_at": store["balances"].get("updated_at")}

def tool_rebuild_balances(path: str) -> Dict[str, Any]:
    p = Path(path)
    store = read_json(p)

    store["balances"] = {"updated_at": None, "by_group": {}, "global": {"net": {}}}

    # Re-apply all debts
    for tx in store.get("transactions", []):
        gid = tx["group_id"]
        store["balances"]["by_group"].setdefault(gid, {"net": {}})
        for d in tx.get("debts", []):
            update_balances_for_debt(store, gid, d["from_user_id"], d["to_user_id"], int(d["amount_cents"]))

    # Apply payments (subtract)
    for pay in store.get("payments", []):
        gid = pay["group_id"]
        store["balances"]["by_group"].setdefault(gid, {"net": {}})
        update_balances_for_debt(store, gid, pay["from_user_id"], pay["to_user_id"], -int(pay["amount_cents"]))

    store["balances"]["updated_at"] = now_iso()
    write_json_atomic(p, store)
    return {"ok": True, "updated_at": store["balances"]["updated_at"]}