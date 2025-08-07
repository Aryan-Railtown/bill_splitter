import streamlit as st
from backend.bill_parser import Item, SpliterOutput


def splitter_window(group_name, members, parsed_bill, to_summary_callback):
    # Avoid empty bill case
    if not parsed_bill or not members:
        st.warning("No bill or no group members found.")
        return

    idx = st.session_state.splitter_user_idx
    person = members[idx]

    st.header(f"Assign Items for: {person}")
    assert isinstance(parsed_bill, SpliterOutput), "Parsed bill is not of type SpliterOutput"
    # List items and allow this person to select/unselect items
    for item_entry in parsed_bill.items:
        item_name = item_entry.item
        cost = item_entry.cost
        assigned = st.session_state.item_assignments.get(item_name, [])
        chosen = st.checkbox(
            f"{item_name} (${cost})",
            value=(person in assigned),
            key=f"{person}_{item_name}_split"
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
            # Call splitter agent with assignments
            import backend.splitter
            split_result = backend.splitter.process(
                members, parsed_bill, st.session_state.item_assignments
            )
            to_summary_callback(split_result)
            st.rerun()