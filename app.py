import streamlit as st

st.set_page_config(
    page_title="Option Matrix",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

import sys, os
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import importlib
def _load(name): return importlib.import_module(name)

from auth    import render_login_page
from styles  import inject_global_css
from persist import save_user_session, restore_user_session

spread_chart       = _load("spread_chart")
multiplier_chart   = _load("multiplier_chart")
iv_calculator      = _load("iv_calculator")
spread_tracker     = _load("spread_tracker")
historical_backtest= _load("historical_backtest")
position_analysis  = _load("position_analysis")
live_bhavcopy      = _load("live_bhavcopy")
strategy_builder   = _load("strategy_builder")
admin_panel        = _load("admin_panel")

inject_global_css()

# ── Session defaults ──────────────────────────────────────────────────────────
_DEFAULTS = {
    "logged_in":False,"username":"","role":"","approved_tools":[],
    "page":"spread","sp_legs_live":[],
    "sp_n_legs":2,"sp_chart_type":"Candlestick","sp_tf":"1m",
    "sp_result":None,"sp_df":None,
    "ht_n_legs":2,"ht_result":None,"ht_df":None,"ht_chart_type":"Line",
    "iv_result":None,"mx_result":None,
    "st_results":[],"st_configs":{},
    "pos_df":None,"sb_result":None,"sb_n_legs":2,
    "bh_result":None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state: st.session_state[k] = v

if not st.session_state.logged_in:
    render_login_page()
    st.stop()

# ── Restore persisted state once per login ────────────────────────────────────
if not st.session_state.get("_session_restored"):
    restore_user_session(st.session_state.username)
    st.session_state._session_restored = True

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:18px 0 10px;">
      <div style="font-size:22px;font-weight:700;color:#d1d4dc;">⚡ Option Matrix</div>
      <div style="font-size:11px;color:#787b86;margin-top:2px;">Professional Options Analytics</div>
    </div><hr style="border-color:#2a2e39;margin:0 0 12px;">""", unsafe_allow_html=True)

    role  = st.session_state.role
    tools = st.session_state.approved_tools
    user  = st.session_state.username

    st.markdown(f"""
    <div style="background:#1e222d;border:1px solid #2a2e39;border-radius:6px;
                padding:10px 14px;margin-bottom:16px;">
      <div style="font-size:12px;font-weight:500;color:#d1d4dc;">👤 {user}</div>
      <div style="font-size:10px;color:#787b86;margin-top:2px;">
        {'🔑 Admin' if role=='admin' else '🔓 Member'} · Session active
      </div>
    </div>""", unsafe_allow_html=True)

    nav_items = []
    if role=="admin" or "spread"     in tools: nav_items.append(("📊","Spread Chart",       "spread"))
    if role=="admin" or "strategy"   in tools: nav_items.append(("🏗️","Strategy Builder",   "strategy"))
    if role=="admin" or "bhavcopy"   in tools: nav_items.append(("📋","Live Bhavcopy",      "bhavcopy"))
    if role=="admin" or "multiplier" in tools: nav_items.append(("✖️","Multiplier",         "multiplier"))
    if role=="admin" or "iv"         in tools: nav_items.append(("🌡️","IV Calculator",      "iv"))
    if role=="admin" or "tracker"    in tools: nav_items.append(("📋","Spread Tracker",     "tracker"))
    if role=="admin" or "backtest"   in tools: nav_items.append(("🕰️","Historical Backtest","backtest"))
    if role=="admin" or "positions"  in tools: nav_items.append(("📂","Position Analysis",  "positions"))
    if role=="admin":                           nav_items.append(("⚙️","Admin Panel",        "admin"))

    for icon, label, key in nav_items:
        active = st.session_state.page == key
        if st.button(f"{icon}  {label}", key=f"nav_{key}",
                     use_container_width=True,
                     type="primary" if active else "secondary"):
            st.session_state.page = key
            save_user_session(user)   # persist on tab switch
            st.rerun()

    st.markdown('<hr style="border-color:#2a2e39;margin:16px 0 8px;">', unsafe_allow_html=True)

    if st.button("🔄  Refresh Token", use_container_width=True, type="secondary",
                 help="Re-authenticate with Fyers (token expires daily)"):
        from fyers_client import refresh_token
        refresh_token()
        st.success("Token cleared. Will re-authenticate on next action.")
        st.rerun()

    if st.button("💾  Save My Inputs", use_container_width=True, type="secondary",
                 help="Save all current inputs to restore after re-login"):
        save_user_session(user)
        st.success("✅ Inputs saved!")

    if st.button("🚪  Logout", use_container_width=True, type="secondary"):
        save_user_session(user)   # save before logout
        st.session_state.logged_in      = False
        st.session_state.username       = ""
        st.session_state.role           = ""
        st.session_state.approved_tools = []
        st.session_state.page           = "spread"
        st.session_state._session_restored = False
        st.rerun()

    st.markdown(
        '<div style="font-size:10px;color:#2a2e39;text-align:center;padding-top:16px;">'
        'Option Matrix v3.0 · Fyers API</div>', unsafe_allow_html=True)


# ── Access gate ───────────────────────────────────────────────────────────────
def gate(tool_key, render_fn):
    if st.session_state.role == "admin" or tool_key in st.session_state.approved_tools:
        render_fn()
    else:
        st.markdown("""
        <div style="text-align:center;padding:80px 20px;">
          <div style="font-size:48px;margin-bottom:16px;">🔒</div>
          <div style="font-size:20px;color:#d1d4dc;font-weight:500;">Access Restricted</div>
          <div style="font-size:14px;color:#787b86;margin-top:8px;">
            Contact admin to get access to this tool.
          </div>
        </div>""", unsafe_allow_html=True)

# ── Router ────────────────────────────────────────────────────────────────────
page = st.session_state.page
if   page == "spread":      gate("spread",     spread_chart.render)
elif page == "strategy":    gate("strategy",   strategy_builder.render)
elif page == "bhavcopy":    gate("bhavcopy",   live_bhavcopy.render)
elif page == "multiplier":  gate("multiplier", multiplier_chart.render)
elif page == "iv":          gate("iv",         iv_calculator.render)
elif page == "tracker":     gate("tracker",    spread_tracker.render)
elif page == "backtest":    gate("backtest",   historical_backtest.render)
elif page == "positions":   gate("positions",  position_analysis.render)
elif page == "admin":
    if st.session_state.role == "admin": admin_panel.render()
    else: st.error("Admin access only.")

# ── Auto-save on every render ─────────────────────────────────────────────────
if st.session_state.logged_in and st.session_state.username:
    save_user_session(st.session_state.username)
