import streamlit as st
import backend.splitter
import backend.tools.data_tools as dt
from pathlib import Path
import asyncio


def summary_page(split_result, paid_by, back_callback):
    st.header("Final Split Summary")
    if not split_result:
        st.info("No result to display.")
        return

    # If we have parsed bill context and haven't persisted it yet, call the Data Manager
    if not st.session_state.get("summary_persisted", False) and st.session_state.get("parsed_bill_for_persist"):
        parsed_bill = st.session_state.get("parsed_bill_for_persist")
        members = st.session_state.get("members_for_persist")
        group_id = st.session_state.get("group_for_persist") or st.session_state.get("selected_group")
        paid_by_name = st.session_state.get("paid_by") or paid_by
        store_path = "data/storge/store.json"

        # Ensure users exist in the store and build member objects with ids
        member_objs = []
        for m in members:
            resp = dt.tool_upsert_user(store_path, m)
            member_objs.append({"id": resp["user_id"], "name": m})

        item_assignments = st.session_state.get("item_assignments", {})

        try:
            balances = asyncio.run(
                backend.splitter.process(
                    store_path,
                    group_id,
                    member_objs,
                    parsed_bill,
                    item_assignments,
                    paid_by_name,
                )
            )
            # Update displayed split_result with authoritative balances
            st.session_state.split_result = balances
            st.session_state.summary_persisted = True
        except Exception as e:
            st.error(f"Failed to persist transaction: {e}")

    st.write(f":money_with_wings: **Paid by**: {paid_by}")
    for person, amount in st.session_state.split_result.items():
        st.write(f"**{person}** owes: `${amount:.2f}`")
    st.markdown("---")
    if st.button("Back to Group"):
        # cleanup persisted context so future uploads work normally
        for k in ["parsed_bill_for_persist", "members_for_persist", "group_for_persist", "summary_persisted"]:
            if k in st.session_state:
                del st.session_state[k]
        back_callback()
        st.rerun()