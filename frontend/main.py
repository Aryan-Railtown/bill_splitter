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
            # ensure the profile appears in friends list
            if name_input not in st.session_state.friends:
                st.session_state.friends.append(name_input)

            # Persist user to JSON store and ensure groups include them
            store_path = "data/storge/store.json"
            # create or get profile user id
            profile_resp = dt.tool_upsert_user(store_path, name_input)
            profile_id = profile_resp["user_id"]

            # ensure all members across groups exist in the store and create groups if missing
            p = Path(store_path)
            store = dt.read_json(p)
            # helper: find group by name
            def find_group_by_name(s, name):
                for g in s.get("groups", []):
                    if g.get("name") == name:
                        return g
                return None

            for gname, members in st.session_state.group_to_members.items():
                member_ids = []
                for m in members:
                    resp = dt.tool_upsert_user(store_path, m)
                    member_ids.append(resp["user_id"])

                grp = find_group_by_name(store, gname)
                if grp is None:
                    # create new group
                    dt.tool_create_group(store_path, gname, member_ids)
                else:
                    # ensure profile is a member
                    if profile_id not in grp.get("member_ids", []):
                        grp.setdefault("member_ids", []).append(profile_id)
                        # ensure balances bucket exists
                        store["balances"].setdefault("by_group", {}).setdefault(grp["id"], {"net": {}})
                        dt.write_json_atomic(p, store)

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