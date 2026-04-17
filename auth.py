import streamlit as st

def check_auth():
    return st.session_state.get("logged_in", False)

def render_login_page():
    st.title("🔐 Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        # Simple hardcoded login (safe for now)
        if username == "admin" and password == "admin":
            st.session_state.logged_in = True
            st.session_state.username = "Admin"
            st.session_state.role = "admin"
            st.session_state.approved_tools = ["spread", "iv", "multiplier"]
            st.rerun()
        else:
            st.error("Invalid username or password")