import streamlit as st

st.set_page_config(
    page_title="Option Matrix",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# ✅ SAFE IMPORTS ONLY
from auth import check_auth, render_login_page

import admin_panel
import iv_calculator
import multiplier_chart
import position_analysis as spread_chart   # using this as spread

# ─── Session defaults ─────────────────────────────────────────────────────────
for key, val in [
    ("logged_in", False),
    ("username", ""),
    ("role", ""),
    ("approved_tools", []),
    ("page", "spread"),
]:
    if key not in st.session_state:
        st.session_state[key] = val

# ─── Login ────────────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    render_login_page()
    st.stop()

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚡ Option Matrix")

    user = st.session_state.username
    role = st.session_state.role
    tools = st.session_state.approved_tools

    st.write(f"👤 {user}")
    st.write("🔑 Admin" if role == "admin" else "🔓 Member")

    if st.button("📊 Spread Chart"):
        st.session_state.page = "spread"

    if role == "admin" or "iv" in tools:
        if st.button("🌡️ IV Calculator"):
            st.session_state.page = "iv"

    if role == "admin" or "multiplier" in tools:
        if st.button("✖️ Multiplier Chart"):
            st.session_state.page = "multiplier"

    if role == "admin":
        if st.button("🛡️ Admin Panel"):
            st.session_state.page = "admin"

    if st.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()

# ─── Access Control ───────────────────────────────────────────────────────────
def gate(tool, func):
    if st.session_state.role == "admin" or tool in st.session_state.approved_tools:
        func()
    else:
        st.error("🔒 Access Denied")

# ─── Routing ──────────────────────────────────────────────────────────────────
page = st.session_state.page

if page == "spread":
    gate("spread", spread_chart.render)

elif page == "iv":
    gate("iv", iv_calculator.render)

elif page == "multiplier":
    gate("multiplier", multiplier_chart.render)

elif page == "admin":
    if st.session_state.role == "admin":
        admin_panel.render()
    else:
        st.error("Admin only")