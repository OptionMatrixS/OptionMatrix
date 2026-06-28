"""auth.py — SQLite-backed authentication and per-tool access control.

Roles: 'admin', 'member', 'pending'. Admins grant tool access per user per tab.

PERSISTENCE CAVEAT: on Streamlit Community Cloud the container filesystem is
ephemeral, so option_matrix.db is wiped on every reboot/redeploy/wake. To make
the system self-heal, the admin account is re-seeded from secrets on every boot
(ADMIN_USERNAME / ADMIN_PASSWORD, default admin / change-me-now). For durable
member accounts, point DB_PATH at a mounted volume or swap in an external DB.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3

import streamlit as st

DB_PATH = "option_matrix.db"

# Tool keys = one per access-controlled tab.
TOOL_KEYS = ["spread", "multiplier", "iv", "tracker", "backtest",
             "positions", "strategy", "bhavcopy", "quiz"]

TOOL_LABELS = {
    "spread": "Spread Chart", "multiplier": "Multiplier", "iv": "IV Calculator",
    "tracker": "Spread Tracker", "backtest": "Historical Backtest",
    "positions": "Position Analysis", "strategy": "Strategy Builder",
    "bhavcopy": "Live Bhavcopy", "quiz": "NISM Quiz",
}

_SALT = "option_matrix_v2"


def _hash(password: str) -> str:
    return hashlib.sha256((_SALT + password).encode()).hexdigest()


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'pending',
                tools TEXT NOT NULL DEFAULT ''
            )""")
        c.commit()
    _seed_admin()


def _secret(key, default=""):
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


def _seed_admin() -> None:
    """Ensure an admin exists (self-heal after an ephemeral-FS reset)."""
    admin_user = _secret("ADMIN_USERNAME", "admin")
    admin_pass = _secret("ADMIN_PASSWORD", "change-me-now")
    with _conn() as c:
        row = c.execute("SELECT username FROM users WHERE username=?",
                        (admin_user,)).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users(username,password,role,tools) VALUES(?,?,?,?)",
                (admin_user, _hash(admin_pass), "admin", ",".join(TOOL_KEYS)))
            c.commit()


# --- Account operations ----------------------------------------------------
def register(username: str, password: str):
    username = (username or "").strip()
    if not username or not password:
        return False, "Username and password required."
    with _conn() as c:
        if c.execute("SELECT 1 FROM users WHERE username=?",
                     (username,)).fetchone():
            return False, "Username already exists."
        c.execute("INSERT INTO users(username,password,role,tools) "
                  "VALUES(?,?,?,?)", (username, _hash(password), "pending", ""))
        c.commit()
    return True, "Registered. An admin must approve your access."


def login(username: str, password: str):
    username = (username or "").strip()
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?",
                        (username,)).fetchone()
    if not row or row["password"] != _hash(password):
        return None
    return {"username": row["username"], "role": row["role"],
            "tools": [t for t in row["tools"].split(",") if t]}


def get_user(username: str):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE username=?",
                        (username,)).fetchone()
    if not row:
        return None
    return {"username": row["username"], "role": row["role"],
            "tools": [t for t in row["tools"].split(",") if t]}


def list_users():
    with _conn() as c:
        rows = c.execute("SELECT username,role,tools FROM users "
                         "ORDER BY role DESC, username").fetchall()
    return [{"username": r["username"], "role": r["role"],
             "tools": [t for t in r["tools"].split(",") if t]} for r in rows]


def set_role(username: str, role: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        if role == "admin":
            c.execute("UPDATE users SET tools=? WHERE username=?",
                      (",".join(TOOL_KEYS), username))
        c.commit()


def set_tools(username: str, tools) -> None:
    clean = [t for t in tools if t in TOOL_KEYS]
    with _conn() as c:
        c.execute("UPDATE users SET tools=? WHERE username=?",
                  (",".join(clean), username))
        c.commit()


def delete_user(username: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM users WHERE username=?", (username,))
        c.commit()


def reset_password(username: str, new_password: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET password=? WHERE username=?",
                  (_hash(new_password), username))
        c.commit()


def can_access(user: dict, tool_key: str) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return tool_key in (user.get("tools") or [])
