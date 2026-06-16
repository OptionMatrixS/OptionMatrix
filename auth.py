"""
SQLite-based user authentication with per-tab tool access control.
"""

import sqlite3
import hashlib
import streamlit as st
from pathlib import Path

DB_PATH = "users.db"

ALL_TOOLS = ["spread", "multiplier", "iv", "tracker", "backtest", "positions", "strategy", "bhavcopy", "quiz"]

TOOL_LABELS = {
    "spread":     "📊 Spread Chart",
    "multiplier": "✖️ Multiplier Chart",
    "iv":         "📈 IV Calculator",
    "tracker":    "🔍 Spread Tracker",
    "backtest":   "🕐 Historical Backtest",
    "positions":  "📋 Position Analysis",
    "strategy":   "🧩 Strategy Builder",
    "bhavcopy":   "📂 Live Bhavcopy",
    "quiz":       "🎓 NISM Quiz",
}


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with _conn() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'member'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tool_access (
                username TEXT,
                tool TEXT,
                PRIMARY KEY (username, tool)
            )
        """)
        # Default admin
        cur.execute("SELECT username FROM users WHERE username='admin'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users VALUES (?, ?, ?)", ("admin", _hash("admin123"), "admin"))
        con.commit()


def verify_login(username: str, password: str) -> tuple[bool, str]:
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT role FROM users WHERE username=? AND password=?",
                    (username, _hash(password)))
        row = cur.fetchone()
        if row:
            return True, row[0]
        return False, ""


def get_users() -> list[dict]:
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT username, role FROM users ORDER BY username")
        return [{"username": r[0], "role": r[1]} for r in cur.fetchall()]


def add_user(username: str, password: str, role: str = "member"):
    with _conn() as con:
        con.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)",
                    (username, _hash(password), role))


def delete_user(username: str):
    with _conn() as con:
        con.execute("DELETE FROM users WHERE username=?", (username,))
        con.execute("DELETE FROM tool_access WHERE username=?", (username,))


def get_user_tools(username: str) -> list[str]:
    with _conn() as con:
        cur = con.cursor()
        cur.execute("SELECT tool FROM tool_access WHERE username=?", (username,))
        return [r[0] for r in cur.fetchall()]


def set_user_tools(username: str, tools: list[str]):
    with _conn() as con:
        con.execute("DELETE FROM tool_access WHERE username=?", (username,))
        for tool in tools:
            con.execute("INSERT OR IGNORE INTO tool_access VALUES (?, ?)", (username, tool))


def has_tool_access(tool: str) -> bool:
    user = st.session_state.get("username", "")
    role = st.session_state.get("role", "")
    if role == "admin":
        return True
    return tool in st.session_state.get("user_tools", [])


def login_ui():
    """Render login form. Returns True if logged in."""
    if st.session_state.get("logged_in"):
        return True

    st.markdown("""
    <div style='max-width:380px;margin:80px auto 0;'>
    <h2 style='color:#d1d4dc;text-align:center;margin-bottom:24px;'>🔷 Option Matrix</h2>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if submitted:
        ok, role = verify_login(username, password)
        if ok:
            st.session_state["logged_in"] = True
            st.session_state["username"]  = username
            st.session_state["role"]      = role
            st.session_state["user_tools"] = get_user_tools(username)
            st.rerun()
        else:
            st.error("Invalid username or password.")
    return False


def admin_panel():
    """Admin user management UI."""
    st.subheader("👤 User Management")
    users = get_users()

    # Add user
    with st.expander("➕ Add New User"):
        with st.form("add_user_form"):
            nu = st.text_input("Username")
            np = st.text_input("Password", type="password")
            nr = st.selectbox("Role", ["member", "admin"])
            if st.form_submit_button("Add User"):
                add_user(nu, np, nr)
                st.success(f"User '{nu}' added.")
                st.rerun()

    # Manage existing users
    for user in users:
        uname = user["username"]
        if uname == "admin":
            continue
        with st.expander(f"🔧 {uname} ({user['role']})"):
            current = get_user_tools(uname)
            selected = st.multiselect(
                "Tool Access",
                options=ALL_TOOLS,
                default=current,
                format_func=lambda t: TOOL_LABELS.get(t, t),
                key=f"tools_{uname}",
            )
            col1, col2 = st.columns(2)
            if col1.button("Save Access", key=f"save_{uname}"):
                set_user_tools(uname, selected)
                st.success("Saved.")
            if col2.button("Delete User", key=f"del_{uname}"):
                delete_user(uname)
                st.rerun()
