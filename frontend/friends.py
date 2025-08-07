# friends.py
import streamlit as st

def friends_grid(friends, friend_to_groups):
    """
    Shows all friends as clickable boxes (but nothing happens on click).
    """
    cols = st.columns(3)
    for idx, friend in enumerate(friends):
        with cols[idx % 3]:
            st.button(friend, key=f'friend_{friend}', help=f"Groups: {', '.join(friend_to_groups[friend])}")