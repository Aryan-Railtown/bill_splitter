import streamlit as st
from data.mock import friends as mock_friends, group_names as mock_group_names, group_to_members as mock_group_to_members, friend_to_groups as mock_friend_to_groups
from friends import friends_grid
import backend.tools.data_tools as dt
from pathlib import Path
from splitter_window import splitter_window
from groups import group_page, group_list
from summary import summary_page

st.set_page_config(page_title="Bill Splitter", layout="wide")
st.title("Bill Splitter")

# ---- UI State Management ----
if "ui_step" not in st.session_state:
    st.session_state.ui_step = "home"  # "home", "splitter_window", "summary"
if "parsed_bill" not in st.session_state:
    st.session_state.parsed_bill = None
if "item_assignments" not in st.session_state:
    st.session_state.item_assignments = {}
if "split_result" not in st.session_state:
    st.session_state.split_result = None
if 'splitter_user_idx' not in st.session_state:
    st.session_state.splitter_user_idx = 0 

# ---- Profile state (who is using the app) ----
if 'profile_name' not in st.session_state:
    st.session_state.profile_name = None

# Initialize app-level friends/groups from the mock data (store editable copies in session)
if 'friends' not in st.session_state:
    st.session_state.friends = list(mock_friends)
if 'group_names' not in st.session_state:
    st.session_state.group_names = list(mock_group_names)
if 'group_to_members' not in st.session_state:
    # make a shallow copy of mapping
    st.session_state.group_to_members = {k: list(v) for k, v in mock_group_to_members.items()}
if 'friend_to_groups' not in st.session_state:
    st.session_state.friend_to_groups = {k: list(v) for k, v in mock_friend_to_groups.items()}

# Simple in-memory ledger stored in session for demo purposes
if 'ledger' not in st.session_state:
    st.session_state.ledger = []

# Profile input in the sidebar
with st.sidebar:
    st.header("Profile")
    name_input = st.text_input("Your display name", value=(st.session_state.profile_name or ""))
    if st.button("Save Profile"):
        if name_input:
            st.session_state.profile_name = name_input
            # ensure the profile appears in friends list and session group members
            if name_input not in st.session_state.friends:
                st.session_state.friends.append(name_input)
            for g in st.session_state.group_to_members:
                if name_input not in st.session_state.group_to_members[g]:
                    st.session_state.group_to_members[g].append(name_input)
                    st.session_state.friend_to_groups.setdefault(name_input, []).append(g)

            # Persist user to JSON store and ensure groups include them
            store_path = "data/storge/store.json"
            # create or get profile user id
            profile_resp = dt.tool_upsert_user(store_path, name_input)
            profile_id = profile_resp["user_id"]

            p = Path(store_path)
            store = dt.read_json(p)

            # Ensure every user in session groups exists in the store (upsert)
            for members in st.session_state.group_to_members.values():
                for m in members:
                    dt.tool_upsert_user(store_path, m)

            # Ensure profile is a member of every group present in the store
            modified = False
            for grp in store.get("groups", []):
                if profile_id not in grp.get("member_ids", []):
                    grp.setdefault("member_ids", []).append(profile_id)
                    modified = True

            if modified:
                dt.write_json_atomic(p, store)

            # Also ensure any groups present in session but missing in store are created
            existing_group_names = {g["name"] for g in store.get("groups", [])}
            for gname, members in st.session_state.group_to_members.items():
                if gname not in existing_group_names:
                    member_ids = [dt.tool_upsert_user(store_path, m)["user_id"] for m in members]
                    dt.tool_create_group(store_path, gname, member_ids)

            st.success(f"Profile saved as {name_input}")
            st.rerun()

def to_splitter(parsed_bill, paid_by):
    st.session_state.parsed_bill = parsed_bill
    st.session_state.ui_step = "splitter_window"
    st.session_state.item_assignments = {}
    st.session_state.splitter_user_idx = 0
    st.session_state.paid_by = paid_by

def to_summary(split_result):
    st.session_state.split_result = split_result
    st.session_state.ui_step = "summary"

def to_home():
    st.session_state.ui_step = "home"
    st.session_state.parsed_bill = None
    st.session_state.item_assignments = {}
    st.session_state.split_result = None
    st.session_state.splitter_user_idx = 0

# ---- Main Logic ----
tab1, tab2 = st.tabs(["Groups", "Friends"])

with tab1:
    if st.session_state.ui_step == "home":
        if 'selected_group' not in st.session_state:
            st.session_state.selected_group = None

        def select_group(group):
            st.session_state.selected_group = group

        if st.session_state.selected_group:
            if st.button("← Back to all groups"):
                st.session_state.selected_group = None
            else:
                # Pass a callback to launch the splitter window
                group_page(
                    st.session_state.selected_group,
                    st.session_state.group_to_members[st.session_state.selected_group],
                    to_splitter,
                )
        else:
            st.header("All Groups")
            group_list(st.session_state.group_names, select_group)

    elif st.session_state.ui_step == "splitter_window":
        splitter_window(
            st.session_state.selected_group,
            st.session_state.group_to_members[st.session_state.selected_group],
            st.session_state.parsed_bill,
            to_summary,
        )

    elif st.session_state.ui_step == "summary":
        summary_page(st.session_state.split_result, st.session_state.paid_by, to_home)

with tab2:
    st.header("Friends")
    # Render friends grid showing balances relative to the saved profile (if any)
    friends_grid(
        st.session_state.friends,
        st.session_state.friend_to_groups,
        store_path="data/storge/store.json",
        profile_name=st.session_state.profile_name,
    )