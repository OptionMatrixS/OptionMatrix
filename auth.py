import streamlit as st
import sqlite3
import hashlib
from datetime import datetime

DB_PATH = "option_matrix.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password      TEXT NOT NULL,
            role          TEXT DEFAULT 'pending',
            approved_tools TEXT DEFAULT '',
            subscription  TEXT DEFAULT 'free',
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    admin_pw = _hash("admin123")
    c.execute("""
        INSERT OR IGNORE INTO users (username, password, role, approved_tools)
        VALUES (?, ?, 'admin', 'spread,multiplier,iv,tracker,backtest,positions')
    """, ("admin", admin_pw))
    conn.commit()
    conn.close()

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def register_user(username: str, password: str) -> tuple:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?,?)",
                  (username.strip(), _hash(password)))
        conn.commit()
        return True, "Account created! Awaiting admin approval."
    except sqlite3.IntegrityError:
        return False, "Username already taken."
    finally:
        conn.close()

def login_user(username: str, password: str) -> tuple:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, role, approved_tools FROM users WHERE username=? AND password=?",
              (username.strip(), _hash(password)))
    row = c.fetchone()
    conn.close()
    if not row:
        return False, {}
    uname, role, tools_str = row
    if role == "pending":
        return False, {"pending": True}
    tools = [t.strip() for t in tools_str.split(",") if t.strip()]
    return True, {"username": uname, "role": role, "tools": tools}

def get_all_users():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute(
        "SELECT username, role, approved_tools FROM users ORDER BY username"
    ).fetchall()
    conn.close()
    return rows

def update_user_tools(username: str, tools: list):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET approved_tools=? WHERE username=?",
              (",".join(tools), username))
    conn.commit()
    conn.close()

def update_user_role(username: str, role: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    conn.commit()
    conn.close()

def delete_user(username: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()

def change_password(username: str, new_password: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET password=? WHERE username=?",
              (_hash(new_password), username))
    conn.commit()
    conn.close()

def upsert_user(username: str, password: str, role: str = "member",
                approved: bool = True, tools: str = ""):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    existing = c.execute(
        "SELECT username FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        c.execute("UPDATE users SET role=?,approved_tools=? WHERE username=?",
                  (role, tools, username))
    else:
        c.execute(
            "INSERT INTO users(username,password,role,approved_tools) VALUES(?,?,?,?)",
            (username.strip(), _hash(password), role, tools))
    conn.commit()
    conn.close()

def render_login_page():
    init_db()
    st.markdown("""
    <div style="max-width:380px;margin:60px auto 0;padding:0 16px;">
      <div style="text-align:center;margin-bottom:32px;">
        <div style="font-size:48px;">⚡</div>
        <div style="font-size:28px;font-weight:700;color:#d1d4dc;
                    letter-spacing:0.03em;">Option Matrix</div>
        <div style="font-size:13px;color:#787b86;margin-top:4px;">
          Professional Options Analytics</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 2, 1])
    with center:
        tab_login, tab_reg = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            username = st.text_input("Username", placeholder="username", key="li_user")
            password = st.text_input("Password", type="password",
                                     placeholder="••••••••", key="li_pw")
            if st.button("Sign In →", use_container_width=True,
                         type="primary", key="btn_login"):
                if not username or not password:
                    st.error("Please fill in all fields.")
                else:
                    ok, info = login_user(username, password)
                    if ok:
                        st.session_state.logged_in      = True
                        st.session_state.username       = info["username"]
                        st.session_state.role           = info["role"]
                        st.session_state.approved_tools = info["tools"]
                        st.session_state.page           = "spread"
                        st.rerun()
                    elif info.get("pending"):
                        st.warning("⏳ Your account is pending admin approval.")
                    else:
                        st.error("Invalid username or password.")

        with tab_reg:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            r_user = st.text_input("Username", placeholder="choose username",
                                   key="reg_user")
            r_pw   = st.text_input("Password", type="password",
                                   placeholder="min 6 chars", key="reg_pw")
            r_pw2  = st.text_input("Confirm Password", type="password",
                                   placeholder="repeat", key="reg_pw2")
            if st.button("Create Account →", use_container_width=True,
                         type="primary", key="btn_reg"):
                if not all([r_user, r_pw, r_pw2]):
                    st.error("Please fill in all fields.")
                elif len(r_pw) < 6:
                    st.error("Password must be at least 6 characters.")
                elif r_pw != r_pw2:
                    st.error("Passwords don't match.")
                else:
                    ok, msg = register_user(r_user, r_pw)
                    st.success(f"✅ {msg}") if ok else st.error(msg)
