import streamlit as st
import backend.bill_parser

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
            parsed_bill = backend.bill_parser.process(uploaded_file)
            upload_callback(parsed_bill)
            st.session_state.show_uploader = False
            st.rerun()