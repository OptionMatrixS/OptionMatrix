"""admin_panel.py — user & access management (admins only)."""

from __future__ import annotations

import streamlit as st

import styles
import auth

P = styles.PALETTE


def render(user):
    if user.get("role") != "admin":
        st.error("Admins only.")
        return

    st.caption("Approve members, assign roles, and grant per-tool access. "
               "Tool access applies to non-admins; admins see everything.")

    users = auth.list_users()
    pending = [u for u in users if u["role"] == "pending"]

    if pending:
        st.markdown(styles.section(f"⏳ Pending approval ({len(pending)})"),
                    unsafe_allow_html=True)
        for u in pending:
            c = st.columns([2, 1, 1])
            c[0].markdown(f"**{u['username']}**")
            if c[1].button("✅ Approve as member", key=f"appr_{u['username']}"):
                auth.set_role(u["username"], "member")
                st.rerun()
            if c[2].button("🗑️ Reject", key=f"rej_{u['username']}"):
                auth.delete_user(u["username"])
                st.rerun()

    st.markdown(styles.section("👥 All users"), unsafe_allow_html=True)
    for u in users:
        with st.expander(f"{u['username']}  ·  {u['role']}",
                         expanded=False):
            is_self_admin = (u["username"] == user["username"])

            c = st.columns([1, 1])
            new_role = c[0].selectbox(
                "Role", ["admin", "member", "pending"],
                index=["admin", "member", "pending"].index(u["role"]),
                key=f"role_{u['username']}")
            if c[1].button("Update role", key=f"setrole_{u['username']}",
                           disabled=is_self_admin):
                auth.set_role(u["username"], new_role)
                st.rerun()
            if is_self_admin:
                c[1].caption("You can't change your own role.")

            if u["role"] != "admin":
                st.markdown("**Tool access**")
                cols = st.columns(3)
                granted = set(u["tools"])
                new_tools = []
                for i, key in enumerate(auth.TOOL_KEYS):
                    on = cols[i % 3].checkbox(
                        auth.TOOL_LABELS[key], value=(key in granted),
                        key=f"tool_{u['username']}_{key}")
                    if on:
                        new_tools.append(key)
                if st.button("💾 Save tools", key=f"savetools_{u['username']}"):
                    auth.set_tools(u["username"], new_tools)
                    st.success("Access updated.")
                    st.rerun()

            st.markdown("**Account actions**")
            ac = st.columns([2, 1])
            pw = ac[0].text_input("Reset password to", type="password",
                                  key=f"pw_{u['username']}")
            if ac[1].button("Reset", key=f"resetpw_{u['username']}"):
                if pw:
                    auth.reset_password(u["username"], pw)
                    st.success("Password reset.")
                else:
                    st.warning("Enter a new password first.")

            if not is_self_admin:
                if st.button("🗑️ Delete user", key=f"del_{u['username']}"):
                    auth.delete_user(u["username"])
                    st.rerun()
