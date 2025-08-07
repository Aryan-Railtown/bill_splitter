import streamlit as st
from data.mock import friends, group_names, group_to_members, friend_to_groups, friends_grid
from splitter_window import splitter_window
from groups import group_page
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

def to_splitter(parsed_bill):
    st.session_state.parsed_bill = parsed_bill
    st.session_state.ui_step = "splitter_window"
    st.session_state.item_assignments = {}
    st.session_state.splitter_user_idx = 0

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
                    group_to_members[st.session_state.selected_group], 
                    to_splitter
                )
        else:
            from groups import group_list
            st.header("All Groups")
            group_list(group_names, select_group)

    elif st.session_state.ui_step == "splitter_window":
        splitter_window(
            st.session_state.selected_group,
            group_to_members[st.session_state.selected_group],
            st.session_state.parsed_bill,
            to_summary,
        )

    elif st.session_state.ui_step == "summary":
        summary_page(st.session_state.split_result, to_home)

with tab2:
    st.header("Friends")
    friends_grid(friends, friend_to_groups)