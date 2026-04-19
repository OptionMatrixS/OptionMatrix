"""admin_panel.py — User management for admin."""

import streamlit as st
from auth import (get_all_users, upsert_user, delete_user,
                  update_user_tools, update_user_role,
                  change_password)

ALL_TOOLS = ["spread","multiplier","iv","tracker","backtest",
             "positions","strategy","bhavcopy"]


def render():
    st.markdown("## ⚙️ Admin Panel")

    tab1, tab2 = st.tabs(["👥 Manage Users", "➕ Add User"])

    with tab1:
        users = get_all_users()
        if not users:
            st.info("No users found.")
            return

        for username, role, tools_str in users:
            if username == st.session_state.get("username"):
                continue
            tool_list = [t for t in tools_str.split(",") if t]
            with st.expander(
                f"👤 {username}  —  {role}  "
                f"{'✅ approved' if role != 'pending' else '⏳ pending'}",
                expanded=False):

                c1, c2, c3 = st.columns(3)
                with c1:
                    new_role = st.selectbox(
                        "Role", ["member","admin","pending"],
                        index=["member","admin","pending"].index(role)
                              if role in ["member","admin","pending"] else 0,
                        key=f"adm_role_{username}")
                with c2:
                    new_pw = st.text_input(
                        "New password (blank = keep)",
                        type="password", key=f"adm_pw_{username}")
                with c3:
                    st.markdown(
                        f'<div style="padding-top:28px;font-size:11px;'
                        f'color:#787b86;">Current: {role}</div>',
                        unsafe_allow_html=True)

                new_tools = st.multiselect(
                    "Tools Access", ALL_TOOLS,
                    default=[t for t in tool_list if t in ALL_TOOLS],
                    key=f"adm_tools_{username}")

                sc1, sc2 = st.columns(2)
                with sc1:
                    if st.button("💾 Save", key=f"adm_save_{username}",
                                 type="primary", use_container_width=True):
                        update_user_role(username, new_role)
                        update_user_tools(username, new_tools)
                        if new_pw:
                            change_password(username, new_pw)
                        st.success(f"Saved {username}")
                        st.rerun()
                with sc2:
                    if st.button("🗑 Delete", key=f"adm_del_{username}",
                                 use_container_width=True):
                        delete_user(username)
                        st.warning(f"Deleted {username}")
                        st.rerun()

    with tab2:
        with st.form("add_user_form"):
            nu  = st.text_input("Username")
            npw = st.text_input("Password", type="password")
            nr  = st.selectbox("Role", ["member","admin"])
            nt  = st.multiselect("Tools", ALL_TOOLS, default=ALL_TOOLS)
            if st.form_submit_button("Add User", type="primary"):
                if nu and npw:
                    upsert_user(nu.strip(), npw, role=nr,
                                approved=True, tools=",".join(nt))
                    st.success(f"User '{nu}' created.")
                    st.rerun()
                else:
                    st.error("Username and password required.")
