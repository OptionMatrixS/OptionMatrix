import streamlit as st

st.set_page_config(
    page_title="Option Matrix",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
# ✅ INLINE LOGIN (NO auth.py NEEDED)
# ─────────────────────────────────────────────────────────

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.approved_tools = []
    st.session_state.page = "spread"

def login_page():
    st.title("🔐 Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username == "admin" and password == "admin":
            st.session_state.logged_in = True
            st.session_state.username = "Admin"
            st.session_state.role = "admin"
            st.session_state.approved_tools = ["spread", "iv", "multiplier"]
            st.rerun()
        else:
            st.error("Invalid credentials")

# ─────────────────────────────────────────────────────────
# IMPORT YOUR MODULES
# ─────────────────────────────────────────────────────────

import admin_panel
import iv_calculator
import multiplier_chart
import position_analysis as spread_chart

# ─────────────────────────────────────────────────────────
# LOGIN CHECK
# ─────────────────────────────────────────────────────────

if not st.session_state.logged_in:
    login_page()
    st.stop()

# ─────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚡ Option Matrix")

    st.write(f"👤 {st.session_state.username}")
    st.write("🔑 Admin" if st.session_state.role == "admin" else "🔓 Member")

    if st.button("📊 Spread Chart"):
        st.session_state.page = "spread"

    if st.button("🌡️ IV Calculator"):
        st.session_state.page = "iv"

    if st.button("✖️ Multiplier Chart"):
        st.session_state.page = "multiplier"

    if st.session_state.role == "admin":
        if st.button("🛡️ Admin Panel"):
            st.session_state.page = "admin"

    if st.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

# ─────────────────────────────────────────────────────────
# ACCESS CONTROL
# ─────────────────────────────────────────────────────────

def gate(func):
    func()

# ─────────────────────────────────────────────────────────
# PAGE ROUTING
# ─────────────────────────────────────────────────────────

page = st.session_state.page

if page == "spread":
    gate(spread_chart.render)

elif page == "iv":
    gate(iv_calculator.render)

elif page == "multiplier":
    gate(multiplier_chart.render)

elif page == "admin":
    if st.session_state.role == "admin":
        admin_panel.render()
    else:
        st.error("Admin only")