"""app.py — Option Matrix entry point.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import json
import os

import streamlit as st

import auth
import styles
import fyers_client as fc

# Tab modules
import spread_chart
import multiplier_chart
import iv_calculator
import spread_tracker
import historical_backtest
import position_analysis
import strategy_builder
import live_bhavcopy
import quiz
import admin_panel

STATE_FILE = "user_state.json"

# Nav registry: (key, icon, label, module, requires_access)
NAV = [
    ("spread",     "📊", "Spread Chart",        spread_chart,       True),
    ("multiplier", "✖️", "Multiplier",          multiplier_chart,   True),
    ("iv",         "🌡️", "IV Calculator",       iv_calculator,      True),
    ("tracker",    "📋", "Spread Tracker",      spread_tracker,     True),
    ("backtest",   "🕰️", "Historical Backtest", historical_backtest, True),
    ("positions",  "📂", "Position Analysis",   position_analysis,  True),
    ("strategy",   "🏗️", "Strategy Builder",    strategy_builder,   True),
    ("bhavcopy",   "📋", "Live Bhavcopy",       live_bhavcopy,      True),
    ("quiz",       "🎓", "NISM Quiz",           quiz,               True),
    ("admin",      "⚙️", "Admin Panel",         admin_panel,        False),
]


# ---------------------------------------------------------------------------
# Cross-session input persistence (user_state.json keyed by username)
# ---------------------------------------------------------------------------
PERSIST_KEYS_PREFIXES = ("legs_", "cfg_", "tracker_", "strategy_", "ui_")


def _serializable(value):
    if isinstance(value, set):
        return list(value)
    try:
        json.dumps(value)
        return value
    except Exception:
        return None  # drop DataFrames / non-serializable objects


def save_state(username: str) -> None:
    if not username:
        return
    snapshot = {}
    for k, v in st.session_state.items():
        if isinstance(k, str) and k.startswith(PERSIST_KEYS_PREFIXES):
            s = _serializable(v)
            if s is not None:
                snapshot[k] = s
    try:
        store = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as fh:
                store = json.load(fh)
        store[username] = snapshot
        with open(STATE_FILE, "w") as fh:
            json.dump(store, fh)
    except Exception:
        pass


def load_state(username: str) -> None:
    if not username:
        return
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as fh:
                store = json.load(fh)
            for k, v in (store.get(username) or {}).items():
                st.session_state.setdefault(k, v)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------
def init_session() -> None:
    defaults = {
        "user": None,
        "active_tab": "spread",
        "ui_chart_type": "Line",
        "ui_timeframe": "1m",
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


# ---------------------------------------------------------------------------
# Login / register screen
# ---------------------------------------------------------------------------
def login_screen() -> None:
    st.markdown(
        f"<h1 style='color:{styles.PALETTE['TEXT']};'>⚡ Option Matrix</h1>"
        f"<div style='color:{styles.PALETTE['MUTED']};margin-top:-10px;'>"
        f"Options analytics · Fyers API v3</div>", unsafe_allow_html=True)
    st.write("")
    tab_login, tab_reg = st.tabs(["🔑 Login", "🆕 Register"])

    with tab_login:
        u = st.text_input("Username", key="login_u")
        p = st.text_input("Password", type="password", key="login_p")
        if st.button("Sign in", key="login_btn"):
            user = auth.login(u, p)
            if not user:
                st.error("Invalid username or password.")
            elif user["role"] == "pending":
                st.warning("Your account is pending admin approval.")
            else:
                st.session_state["user"] = user
                load_state(user["username"])
                st.rerun()

    with tab_reg:
        u2 = st.text_input("Choose a username", key="reg_u")
        p2 = st.text_input("Choose a password", type="password", key="reg_p")
        if st.button("Create account", key="reg_btn"):
            ok, msg = auth.register(u2, p2)
            (st.success if ok else st.error)(msg)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def sidebar(user: dict) -> None:
    s = st.sidebar
    p = styles.PALETTE
    s.markdown(f"<div style='font-size:20px;font-weight:700;'>⚡ Option Matrix</div>",
               unsafe_allow_html=True)
    s.markdown("---")

    role_badge = "🔑 Admin" if user["role"] == "admin" else "🔓 Member"
    s.markdown(f"👤 **{user['username']}** &nbsp; {role_badge}",
               unsafe_allow_html=True)

    is_open, now = fc.market_status()
    dot = "🟢 OPEN" if is_open else "🔴 CLOSED"
    color = p["GREEN"] if is_open else p["RED"]
    s.markdown(
        f"<div style='background:{p['PANEL']};border:1px solid {p['BORDER']};"
        f"border-radius:6px;padding:6px 10px;font-size:12px;'>"
        f"Market <span style='color:{color};font-weight:700;'>{dot}</span> · "
        f"{now.strftime('%H:%M:%S')} IST</div>", unsafe_allow_html=True)
    s.markdown("---")

    for key, icon, label, _mod, needs in NAV:
        if key == "admin" and user["role"] != "admin":
            continue
        if needs and not auth.can_access(user, key):
            continue
        if s.button(f"{icon} {label}", key=f"nav_{key}", use_container_width=True):
            save_state(user["username"])
            st.session_state["active_tab"] = key
            st.rerun()

    s.markdown("---")
    c1, c2 = s.columns(2)
    if c1.button("🔄 Token", key="btn_token", use_container_width=True):
        try:
            fc.refresh_token()
            s.success("Token refreshed.")
        except Exception as e:
            s.error(f"Token error: {e}")
    if c2.button("💾 Save", key="btn_save", use_container_width=True):
        save_state(user["username"])
        s.success("Inputs saved.")

    if s.button("🚪 Logout", key="btn_logout", use_container_width=True):
        save_state(user["username"])
        st.session_state["user"] = None
        st.session_state["active_tab"] = "spread"
        st.rerun()

    s.markdown("---")
    s.markdown(f"<div style='font-size:10px;color:{p['MUTED']};'>"
               f"Option Matrix v2.0 · Fyers API v3</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Option Matrix", page_icon="⚡",
                       layout="wide", initial_sidebar_state="expanded")
    styles.inject_css()
    auth.init_db()
    init_session()

    user = st.session_state.get("user")
    if not user:
        login_screen()
        return

    sidebar(user)

    active = st.session_state.get("active_tab", "spread")
    for key, icon, label, mod, needs in NAV:
        if key == active:
            if key == "admin":
                if user["role"] != "admin":
                    st.error("Admins only.")
                    return
            elif needs and not auth.can_access(user, key):
                st.error("You don't have access to this tool. Ask an admin.")
                return
            st.markdown(f"### {icon} {label}")
            try:
                mod.render(user)
            except Exception as e:
                st.error(f"Error in {label}: {e}")
                st.exception(e)
            return
    st.info("Select a tool from the sidebar.")


if __name__ == "__main__":
    main()
