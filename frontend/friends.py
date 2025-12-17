# friends.py
import streamlit as st
from pathlib import Path
import backend.tools.data_tools as dt


def friends_grid(friends, friend_to_groups, store_path: str = "data/storge/store.json", profile_name: str | None = None):
    """
    Shows all friends and displays net balance relative to `profile_name`, reading data from the
    persistent JSON store at `store_path`.

    Positive net => friend owes the profile. Negative net => profile owes the friend.
    """
    p = Path(store_path)
    store = dt.read_json(p)

    # Build name -> user_id map
    name_to_id = {u["name"]: u["id"] for u in store.get("users", [])}

    profile_id = None
    if profile_name:
        profile_id = name_to_id.get(profile_name)

    # Build group name -> id map
    group_name_to_id = {g["name"]: g["id"] for g in store.get("groups", [])}

    # Initialize nets for display
    nets = {f: 0.0 for f in friends}
    if profile_name and profile_id:
        nets.setdefault(profile_name, 0.0)

        # For each group in the store, fetch edges and accumulate amounts that involve profile
        for g in store.get("groups", []):
            gid = g["id"]
            balances = dt.tool_get_group_balances(store_path, gid)
            for edge in balances.get("edges", []):
                frm = edge["from_user_id"]
                to = edge["to_user_id"]
                amt = int(edge["amount_cents"]) / 100.0
                # If the edge is friend -> profile, friend owes profile (positive)
                if to == profile_id:
                    # map id -> name if present
                    for name, uid in name_to_id.items():
                        if uid == frm and name in nets:
                            nets[name] += amt
                # If the edge is profile -> friend, profile owes them (negative)
                if frm == profile_id:
                    for name, uid in name_to_id.items():
                        if uid == to and name in nets:
                            nets[name] -= amt

    cols = st.columns(3)
    for idx, friend in enumerate(friends):
        with cols[idx % 3]:
            net = nets.get(friend, 0.0)
            label = f"{friend} (You)" if friend == profile_name else friend
            color = "green" if net > 0 else ("red" if net < 0 else "black")
            amount_str = f"{net:+.2f}"
            st.markdown(f"**{label}**<br/><span style='color:{color}'>${amount_str}</span>", unsafe_allow_html=True)
            st.write(f"Groups: {', '.join(friend_to_groups.get(friend, []))}")