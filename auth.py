import streamlit as st
import sqlite3
import hashlib
import os
from datetime import datetime

DB_PATH = "option_matrix.db"

# ─── DB init ──────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT DEFAULT 'pending',
            approved_tools TEXT DEFAULT '',
            subscription TEXT DEFAULT 'free',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            approved_at TEXT
        )
    """)
    # Ensure default admin exists
    admin_pw = _hash("admin123")
    c.execute("""
        INSERT OR IGNORE INTO users (username, email, password, role, approved_tools)
        VALUES (?, ?, ?, 'admin', 'spread,iv,multiplier')
    """, ("admin", "admin@optionmatrix.com", admin_pw))
    conn.commit()
    conn.close()


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def register_user(username: str, email: str, password: str) -> tuple[bool, str]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, email, password) VALUES (?,?,?)",
            (username.strip(), email.strip().lower(), _hash(password))
        )
        conn.commit()
        return True, "Account created! Awaiting admin approval."
    except sqlite3.IntegrityError as e:
        msg = "Username already taken." if "username" in str(e) else "Email already registered."
        return False, msg
    finally:
        conn.close()


def login_user(username: str, password: str) -> tuple[bool, dict]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT username, role, approved_tools, subscription FROM users WHERE username=? AND password=?",
        (username.strip(), _hash(password))
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return False, {}
    username_, role, tools_str, sub = row
    if role == "pending":
        return False, {"pending": True}
    tools = [t.strip() for t in tools_str.split(",") if t.strip()]
    return True, {"username": username_, "role": role, "tools": tools, "subscription": sub}


def check_auth():
    return st.session_state.get("logged_in", False)


# ─── Login / Register page ────────────────────────────────────────────────────
def render_login_page():
    init_db()

    st.markdown("""
    <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;
                background:#131722;position:fixed;top:0;left:0;right:0;bottom:0;z-index:-1;">
    </div>
    <div style="max-width:420px;margin:60px auto 0;padding:0 16px;">
      <div style="text-align:center;margin-bottom:32px;">
        <div style="font-size:42px;margin-bottom:8px;">⚡</div>
        <div style="font-size:28px;font-weight:700;color:#d1d4dc;letter-spacing:0.03em;">
          Option Matrix
        </div>
        <div style="font-size:13px;color:#787b86;margin-top:6px;">
          Professional Options Analytics Platform
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 2, 1])
    with center:
        tab_login, tab_reg = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            username = st.text_input("Username", placeholder="your_username", key="li_user")
            password = st.text_input("Password", type="password", placeholder="••••••••", key="li_pw")
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            if st.button("Sign In →", use_container_width=True, type="primary", key="btn_login"):
                if not username or not password:
                    st.error("Please fill in all fields.")
                else:
                    ok, info = login_user(username, password)
                    if ok:
                        st.session_state.logged_in = True
                        st.session_state.username = info["username"]
                        st.session_state.role = info["role"]
                        st.session_state.approved_tools = info["tools"]
                        st.session_state.page = "spread"
                        st.rerun()
                    elif info.get("pending"):
                        st.warning("⏳ Your account is pending admin approval.")
                    else:
                        st.error("Invalid username or password.")

            st.markdown("""
            <div style="font-size:11px;color:#787b86;text-align:center;margin-top:12px;">
              Default admin: <code style="color:#2962ff;">admin</code> /
              <code style="color:#2962ff;">admin123</code>
            </div>
            """, unsafe_allow_html=True)

        with tab_reg:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            r_user = st.text_input("Username", placeholder="choose_username", key="reg_user")
            r_email = st.text_input("Email", placeholder="you@email.com", key="reg_email")
            r_pw = st.text_input("Password", type="password", placeholder="min 6 chars", key="reg_pw")
            r_pw2 = st.text_input("Confirm Password", type="password", placeholder="repeat password", key="reg_pw2")
            st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

            if st.button("Create Account →", use_container_width=True, type="primary", key="btn_reg"):
                if not all([r_user, r_email, r_pw, r_pw2]):
                    st.error("Please fill in all fields.")
                elif len(r_pw) < 6:
                    st.error("Password must be at least 6 characters.")
                elif r_pw != r_pw2:
                    st.error("Passwords don't match.")
                elif "@" not in r_email:
                    st.error("Enter a valid email.")
                else:
                    ok, msg = register_user(r_user, r_email, r_pw)
                    if ok:
                        st.success(f"✅ {msg}")
                    else:
                        st.error(msg)
