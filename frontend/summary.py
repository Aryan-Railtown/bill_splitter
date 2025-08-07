import streamlit as st

def summary_page(split_result, back_callback):
    st.header("Final Split Summary")
    if not split_result:
        st.info("No result to display.")
        return

    for person, amount in split_result.items():
        st.write(f"**{person}** owes: `${amount:.2f}`")
    st.markdown("---")
    if st.button("Back to Group"):
        back_callback()
        st.rerun()