"""pages/admin_panel.py — Admin dashboard for Option Matrix"""

import streamlit as st
import sqlite3
from auth import DB_PATH, init_db, _hash

ALL_TOOLS = ["spread", "iv", "multiplier"]
TOOL_LABELS = {"spread": "📊 Spread Chart", "iv": "🌡️ IV Calculator", "multiplier": "✖️ Multiplier"}
SUB_OPTIONS = ["free", "basic_5", "basic_10", "premium"]


def _get_all_users():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, email, role, approved_tools, subscription, created_at FROM users ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def _update_user(user_id, role, tools_list, subscription):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    tools_str = ",".join(tools_list)
    approved_at = "CURRENT_TIMESTAMP" if role == "member" else "NULL"
    c.execute(f"""
        UPDATE users
        SET role=?, approved_tools=?, subscription=?, approved_at={approved_at}
        WHERE id=?
    """, (role, tools_str, subscription, user_id))
    conn.commit()
    conn.close()


def _delete_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=? AND role != 'admin'", (user_id,))
    conn.commit()
    conn.close()


def _reset_password(user_id, new_pw):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET password=? WHERE id=?", (_hash(new_pw), user_id))
    conn.commit()
    conn.close()


def render():
    init_db()
    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
      <div style="font-size:20px;font-weight:600;color:#d1d4dc;">🛡️ Admin Panel</div>
      <div style="font-size:11px;color:#ef5350;padding:3px 10px;background:#2b0d0d;
                  border:1px solid #ef535040;border-radius:10px;">Admin Only</div>
    </div>
    """, unsafe_allow_html=True)

    users = _get_all_users()
    pending = [u for u in users if u[3] == "pending"]
    members = [u for u in users if u[3] not in ("admin", "pending")]
    admins  = [u for u in users if u[3] == "admin"]

    # ── Summary cards ─────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    for col, label, val, color in [
        (m1, "Total Users",    len(users),   "#d1d4dc"),
        (m2, "Pending",        len(pending), "#ff9800"),
        (m3, "Active Members", len(members), "#26a69a"),
        (m4, "Admins",         len(admins),  "#2962ff"),
    ]:
        with col:
            st.markdown(
                f'<div class="stat-chip">'
                f'<div class="sc-label">{label}</div>'
                f'<div class="sc-val" style="color:{color};">{val}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    tab_pending, tab_members, tab_add = st.tabs([
        f"⏳ Pending ({len(pending)})",
        f"👥 All Members ({len(members)})",
        "➕ Add User",
    ])

    # ══════════════════════════════════
    # PENDING APPROVALS
    # ══════════════════════════════════
    with tab_pending:
        if not pending:
            st.markdown("""
            <div style="text-align:center;padding:40px;color:#787b86;">
              <div style="font-size:28px;margin-bottom:8px;">✅</div>
              No pending approvals
            </div>
            """, unsafe_allow_html=True)
        else:
            for u in pending:
                uid, uname, email, role, tools_str, sub, created = u
                with st.expander(f"⏳ {uname}  —  {email}", expanded=True):
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        sel_tools = st.multiselect(
                            "Grant access to",
                            options=ALL_TOOLS,
                            format_func=lambda x: TOOL_LABELS[x],
                            default=["spread"],
                            key=f"pend_tools_{uid}"
                        )
                        sel_sub = st.selectbox(
                            "Subscription plan",
                            SUB_OPTIONS,
                            key=f"pend_sub_{uid}"
                        )
                    with c2:
                        st.markdown(f"""
                        <div style="font-size:11px;color:#787b86;margin-bottom:8px;">
                          Registered: {created[:16] if created else '—'}
                        </div>
                        """, unsafe_allow_html=True)
                        if st.button("✅ Approve", key=f"approve_{uid}", type="primary"):
                            _update_user(uid, "member", sel_tools, sel_sub)
                            st.success(f"Approved {uname}")
                            st.rerun()
                        if st.button("❌ Reject & Delete", key=f"reject_{uid}"):
                            _delete_user(uid)
                            st.warning(f"Deleted {uname}")
                            st.rerun()

    # ══════════════════════════════════
    # MANAGE MEMBERS
    # ══════════════════════════════════
    with tab_members:
        if not members:
            st.info("No approved members yet.")
        else:
            search = st.text_input("🔍 Search by username or email", key="admin_search",
                                   placeholder="Filter users...")
            filtered = [u for u in members if
                        (search.lower() in u[1].lower() or search.lower() in u[2].lower())] \
                       if search else members

            for u in filtered:
                uid, uname, email, role, tools_str, sub, created = u
                current_tools = [t.strip() for t in tools_str.split(",") if t.strip()]

                with st.expander(f"👤 {uname}  ·  {email}  ·  {sub}", expanded=False):
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1:
                        new_tools = st.multiselect(
                            "Tool access",
                            options=ALL_TOOLS,
                            format_func=lambda x: TOOL_LABELS[x],
                            default=[t for t in current_tools if t in ALL_TOOLS],
                            key=f"tools_{uid}"
                        )
                        new_sub = st.selectbox(
                            "Subscription",
                            SUB_OPTIONS,
                            index=SUB_OPTIONS.index(sub) if sub in SUB_OPTIONS else 0,
                            key=f"sub_{uid}"
                        )
                        new_role = st.selectbox(
                            "Role",
                            ["member", "admin"],
                            index=0 if role == "member" else 1,
                            key=f"role_{uid}"
                        )

                    with c2:
                        st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
                        if st.button("💾 Save", key=f"save_{uid}", type="primary"):
                            _update_user(uid, new_role, new_tools, new_sub)
                            st.success("Updated!")
                            st.rerun()

                        if st.button("🗑️ Delete", key=f"del_{uid}"):
                            _delete_user(uid)
                            st.warning(f"Deleted {uname}")
                            st.rerun()

                    with c3:
                        st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
                        new_pw = st.text_input("Reset password", type="password",
                                               placeholder="new password",
                                               key=f"rpw_{uid}")
                        if st.button("🔑 Reset PW", key=f"rpw_btn_{uid}"):
                            if len(new_pw) >= 6:
                                _reset_password(uid, new_pw)
                                st.success("Password reset.")
                            else:
                                st.error("Min 6 chars.")

    # ══════════════════════════════════
    # ADD USER MANUALLY
    # ══════════════════════════════════
    with tab_add:
        st.markdown('<div class="sec-header">Create user account</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            nu = st.text_input("Username", key="add_user")
            ne = st.text_input("Email", key="add_email")
            np_ = st.text_input("Password", type="password", key="add_pw")
        with c2:
            nr = st.selectbox("Role", ["member", "admin"], key="add_role")
            nt = st.multiselect("Tool access", options=ALL_TOOLS,
                                format_func=lambda x: TOOL_LABELS[x],
                                default=["spread"], key="add_tools")
            ns = st.selectbox("Subscription", SUB_OPTIONS, key="add_sub")

        if st.button("➕ Create User", type="primary"):
            if not all([nu, ne, np_]):
                st.error("Fill in all fields.")
            elif len(np_) < 6:
                st.error("Password min 6 chars.")
            else:
                from auth import register_user
                ok, msg = register_user(nu, ne, np_)
                if ok:
                    conn = sqlite3.connect(DB_PATH)
                    c = conn.cursor()
                    c.execute(
                        "UPDATE users SET role=?, approved_tools=?, subscription=? WHERE username=?",
                        (nr, ",".join(nt), ns, nu)
                    )
                    conn.commit()
                    conn.close()
                    st.success(f"✅ Created user '{nu}' with role '{nr}'")
                    st.rerun()
                else:
                    st.error(msg)

    # ── Quick guide ───────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📋 Subscription Plans Guide", expanded=False):
        st.markdown("""
        | Plan | Price | Tools |
        |------|-------|-------|
        | `free` | ₹0 | None (pending manual grant) |
        | `basic_5` | ₹5 / month | Spread Chart |
        | `basic_10` | ₹10 / month | Spread + IV Calculator |
        | `premium` | Custom | All tools |

        > Grant individual tools via the multiselect regardless of plan. Plans are informational for now — you can wire up Razorpay/UPI later.
        """)
