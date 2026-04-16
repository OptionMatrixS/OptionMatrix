import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import sqlite3
from auth import DB_PATH, init_db, _hash

ALL_TOOLS   = ["spread","multiplier","iv","tracker","backtest","positions"]
TOOL_LABELS = {
    "spread":     "📊 Spread Chart",
    "multiplier": "✖️ Multiplier",
    "iv":         "🌡️ IV Calculator",
    "tracker":    "📋 Spread Tracker",
    "backtest":   "🕰️ Historical Backtest",
    "positions":  "📂 Position Analysis",
}
SUB_OPTIONS = ["free","basic_5","basic_10","premium"]

def _get_users():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id,username,role,approved_tools,subscription,created_at FROM users ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def _update_user(uid, role, tools, sub):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET role=?,approved_tools=?,subscription=? WHERE id=?",
              (role, ",".join(tools), sub, uid))
    conn.commit()
    conn.close()

def _delete_user(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=? AND role!='admin'", (uid,))
    conn.commit()
    conn.close()

def _reset_pw(uid, pw):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET password=? WHERE id=?", (_hash(pw), uid))
    conn.commit()
    conn.close()

def render():
    init_db()
    st.markdown('<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:8px;">⚙️ Admin Panel</div>',
                unsafe_allow_html=True)

    users   = _get_users()
    pending = [u for u in users if u[2]=="pending"]
    members = [u for u in users if u[2] not in ("admin","pending")]

    m1,m2,m3,m4 = st.columns(4)
    for col,label,val,color in [
        (m1,"Total Users",len(users),"#d1d4dc"),
        (m2,"Pending",len(pending),"#ff9800"),
        (m3,"Members",len(members),"#26a69a"),
        (m4,"Admins",len([u for u in users if u[2]=="admin"]),"#2962ff"),
    ]:
        with col:
            st.markdown(f'<div class="stat-chip"><div class="sc-label">{label}</div>'
                        f'<div class="sc-val" style="color:{color};">{val}</div></div>',
                        unsafe_allow_html=True)

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
    tab_p, tab_m, tab_add = st.tabs([f"⏳ Pending ({len(pending)})",
                                      f"👥 Members ({len(members)})", "➕ Add User"])

    with tab_p:
        if not pending:
            st.markdown('<div style="text-align:center;padding:40px;color:#787b86;">✅ No pending approvals</div>',
                        unsafe_allow_html=True)
        for u in pending:
            uid,uname,role,tools_str,sub,created = u
            with st.expander(f"⏳ {uname}", expanded=True):
                c1,c2 = st.columns([2,1])
                with c1:
                    sel_tools = st.multiselect("Grant tools", ALL_TOOLS,
                                               format_func=lambda x:TOOL_LABELS[x],
                                               default=["spread"], key=f"pt_{uid}")
                    sel_sub   = st.selectbox("Plan", SUB_OPTIONS, key=f"ps_{uid}")
                with c2:
                    if st.button("✅ Approve", key=f"app_{uid}", type="primary"):
                        _update_user(uid,"member",sel_tools,sel_sub)
                        st.success(f"Approved {uname}"); st.rerun()
                    if st.button("❌ Reject", key=f"rej_{uid}"):
                        _delete_user(uid)
                        st.warning(f"Deleted {uname}"); st.rerun()

    with tab_m:
        search = st.text_input("🔍 Search", placeholder="username...", key="adm_search")
        filtered = [u for u in members if search.lower() in u[1].lower()] if search else members
        for u in filtered:
            uid,uname,role,tools_str,sub,created = u
            cur_tools = [t.strip() for t in tools_str.split(",") if t.strip()]
            with st.expander(f"👤 {uname}  ·  {sub}"):
                c1,c2,c3 = st.columns([2,1,1])
                with c1:
                    new_tools = st.multiselect("Tools", ALL_TOOLS,
                                               format_func=lambda x:TOOL_LABELS[x],
                                               default=[t for t in cur_tools if t in ALL_TOOLS],
                                               key=f"mt_{uid}")
                    new_sub   = st.selectbox("Plan", SUB_OPTIONS,
                                             index=SUB_OPTIONS.index(sub) if sub in SUB_OPTIONS else 0,
                                             key=f"ms_{uid}")
                    new_role  = st.selectbox("Role", ["member","admin"],
                                             index=0 if role=="member" else 1,
                                             key=f"mr_{uid}")
                with c2:
                    if st.button("💾 Save", key=f"sv_{uid}", type="primary"):
                        _update_user(uid,new_role,new_tools,new_sub)
                        st.success("Saved"); st.rerun()
                    if st.button("🗑️ Delete", key=f"dl_{uid}"):
                        _delete_user(uid); st.rerun()
                with c3:
                    npw = st.text_input("New PW", type="password", key=f"npw_{uid}")
                    if st.button("🔑 Reset", key=f"rp_{uid}"):
                        if len(npw) >= 6:
                            _reset_pw(uid,npw); st.success("Reset")
                        else:
                            st.error("Min 6 chars")

    with tab_add:
        st.markdown('<div class="sec-header">Create Account</div>', unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        with c1:
            nu = st.text_input("Username", key="add_u")
            np_ = st.text_input("Password", type="password", key="add_p")
        with c2:
            nr = st.selectbox("Role", ["member","admin"], key="add_r")
            nt = st.multiselect("Tools", ALL_TOOLS, format_func=lambda x:TOOL_LABELS[x],
                                default=["spread"], key="add_t")
            ns = st.selectbox("Plan", SUB_OPTIONS, key="add_s")
        if st.button("➕ Create", type="primary"):
            if not all([nu,np_]) or len(np_)<6:
                st.error("Fill username + password (min 6 chars)")
            else:
                from auth import register_user
                ok,msg = register_user(nu,np_)
                if ok:
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE users SET role=?,approved_tools=?,subscription=? WHERE username=?",
                                 (nr,",".join(nt),ns,nu))
                    conn.commit(); conn.close()
                    st.success(f"✅ Created {nu}"); st.rerun()
                else:
                    st.error(msg)
