from frontend.groups import group_list, group_page
from frontend.friends import friends_grid
import random
import streamlit as st

# ----- Mock Data -----
friends = [
    "Amir", "Logan", "Levi", "Tristan", "Jamie",
    "Chris", "Guan", "Marwan", "Matthew", "Elliot"
]

group_names = ["RT_DEV", "Food", "Random"]

# Fixed assignments
group_to_members = {
    "RT_DEV": ["Amir", "Logan", "Levi", "Tristan", "Jamie", "Guan"],
    "Food": ["Chris", "Guan", "Marwan", "Matthew", "Elliot"],
}

if "group3_members" not in st.session_state:
    # Choose 3 random members for group 3, on app start only
    group3_fixed = random.sample(friends, 3)
    group_to_members["Random"] = group3_fixed
    st.session_state.group3_members = group3_fixed
else:
    group_to_members["Random"] = st.session_state.group3_members

# Reverse mapping for friends tab (handy for your friend grid)
friend_to_groups = {f: [] for f in friends}
for group, members in group_to_members.items():
    for f in members:
        friend_to_groups[f].append(group)