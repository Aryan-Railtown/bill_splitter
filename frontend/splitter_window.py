import streamlit as st
import backend.splitter
import asyncio

def splitter_window(group_name, members, parsed_bill, to_summary_callback):
    # Avoid empty bill case
    if not parsed_bill or not members:
        st.warning("No bill or no group members found.")
        return

    idx = st.session_state.splitter_user_idx
    person = members[idx]

    st.header(f"Assign Items for: {person}")
    # List items and allow this person to select/unselect items
    for item_entry in parsed_bill.items:
        item_name = item_entry.item
        cost = item_entry.cost
        assigned = st.session_state.item_assignments.get(item_name, [])
        chosen = st.checkbox(
            f"{item_name} (${cost})",
            value=(person in assigned),
            key=f"{person}_{item_name}_split",
        )
        if chosen:
            if person not in assigned:
                assigned.append(person)
        else:
            if person in assigned:
                assigned.remove(person)
        st.session_state.item_assignments[item_name] = assigned

    st.markdown("---")
    colprev, colcenter, colnext = st.columns([1, 7, 1])
    with colprev:
        if idx > 0 and st.button("← Prev"):
            st.session_state.splitter_user_idx -= 1
            st.rerun()
    with colnext:
        if idx < len(members) - 1 and st.button("Next →"):
            st.session_state.splitter_user_idx += 1
            st.rerun()
        elif idx == len(members) - 1 and st.button("Split/Process"):
            # backend.splitter.process signature changed to:
            # async def process(store_path, group_id, members, parsed_bill, item_assignments, paid_by, ...)
            # Build minimal member dicts (id/name) from the simple name list used in the UI.
            member_objs = [{"id": m, "name": m} for m in members]
            store_path = "data/storge/store.json"
            group_id = group_name
            try:
                split_result = asyncio.run(
                    backend.splitter.process(
                        store_path,
                        group_id,
                        member_objs,
                        parsed_bill,
                        st.session_state.item_assignments,
                        st.session_state.paid_by,
                    )
                )
            except Exception as e:
                st.error(f"Failed to process split: {e}")
                split_result = None
            to_summary_callback(split_result)
            st.rerun()
