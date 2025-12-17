import streamlit as st
import backend.bill_parser
import asyncio

async def process_bill(uploaded_file):
    return await backend.bill_parser.process(uploaded_file)

def group_list(groups, select_group):
    for group in groups:
        if st.button(group, key=group):
            select_group(group)

def group_page(group_name, members, upload_callback):
    st.header(f"Group: {group_name}")
    st.subheader("Members")
    for person in members:
        st.markdown(f":bust_in_silhouette: **{person}**", unsafe_allow_html=True)
    st.markdown("---")
    if "show_uploader" not in st.session_state:
        st.session_state.show_uploader = False

    if not st.session_state.show_uploader:
        if st.button("Upload Split Bill"):
            st.session_state.show_uploader = True
    else:
        uploaded_file = st.file_uploader("Upload bill image", type=["jpg", "jpeg", "png"])
        if uploaded_file:
            st.success("Bill image uploaded! LLM is processing...")
            parsed_bill = asyncio.run(process_bill(uploaded_file))  # Await the async function
            st.session_state.bill_upload_pending_paid_by = True
            st.session_state.temp_parsed_bill = parsed_bill
            st.session_state.show_uploader = False
            st.rerun()

    # Who paid selection modal
    if st.session_state.get("bill_upload_pending_paid_by", False):
        st.markdown("### Who paid the bill?")
        paid_by = st.selectbox("Select the person who paid:", members, key="paid_by_select")
        if st.button("Confirm Paid By"):
            st.session_state.paid_by = paid_by
            # Move to split choice step (equal by default)
            st.session_state.bill_upload_pending_paid_by = False
            st.session_state.bill_upload_pending_split_choice = True
            st.rerun()

    # After confirming who paid, choose split method
    if st.session_state.get("bill_upload_pending_split_choice", False):
        st.markdown("### How would you like to split the bill?")
        split_choice = st.radio(
            "Choose split method:", ["Split equally (default)", "Split unequally"],
            index=0,
            key="split_choice_radio",
        )

        parsed_bill = st.session_state.get("temp_parsed_bill")
        paid_by = st.session_state.get("paid_by")

        if split_choice.startswith("Split equally"):
            if st.button("Confirm Equal Split"):
                # Compute equal split locally and go to summary
                members_list = members
                total = sum(item.cost for item in parsed_bill.items) if parsed_bill else 0.0
                share = round(total / len(members_list), 2) if members_list else 0.0
                split_result = {
                    m: (0.0 if m == paid_by else share) for m in members_list
                }
                # Store result and navigate to summary
                st.session_state.split_result = split_result
                # Save parsed bill and context so the Data Manager can persist the transaction
                st.session_state.parsed_bill_for_persist = parsed_bill
                st.session_state.members_for_persist = members_list
                st.session_state.group_for_persist = group_name
                # Persist a simple ledger entry in session_state for demo purposes
                if 'ledger' not in st.session_state:
                    st.session_state.ledger = []
                debts = []
                for m in members_list:
                    if m == paid_by:
                        continue
                    amt = 0.0 if m == paid_by else share
                    if amt > 0:
                        debts.append({'from': m, 'to': paid_by, 'amount': amt, 'group': group_name})
                st.session_state.ledger.append({'group': group_name, 'paid_by': paid_by, 'debts': debts})
                st.session_state.ui_step = "summary"
                # cleanup
                st.session_state.bill_upload_pending_split_choice = False
                # keep parsed bill around in parsed_bill_for_persist; remove temp_parsed_bill
                if "temp_parsed_bill" in st.session_state:
                    del st.session_state.temp_parsed_bill
                st.rerun()
        else:
            if st.button("Split Unequally / Go to Splitter"):
                # Send to the splitter window for manual unequal assignments
                if parsed_bill and paid_by:
                    upload_callback(parsed_bill, paid_by)
                st.session_state.bill_upload_pending_split_choice = False
                if "temp_parsed_bill" in st.session_state:
                    del st.session_state.temp_parsed_bill
                st.rerun()