import streamlit as st

def inject_global_css():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html,body,[class*="css"],.stApp{font-family:'IBM Plex Sans',sans-serif!important;background-color:#131722!important;color:#d1d4dc!important;}
.main .block-container{background:#131722;padding:1.2rem 1.8rem 2rem;max-width:100%;}
[data-testid="stSidebar"]{background:#1a1f2e!important;border-right:1px solid #2a2e39!important;}
[data-testid="stSidebar"] *{color:#d1d4dc!important;}
[data-testid="stSidebar"] button{background:transparent!important;border:1px solid #2a2e39!important;border-radius:6px!important;font-size:13px!important;text-align:left!important;padding:8px 14px!important;margin-bottom:4px!important;}
[data-testid="stSidebar"] button[kind="primary"]{background:#162040!important;border-color:#2962ff!important;color:#2962ff!important;}
[data-testid="stSidebar"] button:hover{background:#2a2e39!important;}
div[data-baseweb="select"]>div{background:#1e222d!important;border:1px solid #2a2e39!important;border-radius:4px!important;color:#d1d4dc!important;font-size:12px!important;}
div[data-baseweb="select"] *{color:#d1d4dc!important;font-size:12px!important;}
div[data-baseweb="popover"]{background:#1e222d!important;border:1px solid #2a2e39!important;}
li[role="option"]{background:#1e222d!important;}
li[role="option"]:hover{background:#2a2e39!important;}
input[type="number"],input[type="text"],input[type="password"]{background:#1e222d!important;border:1px solid #2a2e39!important;border-radius:4px!important;color:#d1d4dc!important;font-size:13px!important;}
.stButton>button{background:#1e222d!important;color:#d1d4dc!important;border:1px solid #2a2e39!important;border-radius:4px!important;font-size:13px!important;font-weight:500!important;}
.stButton>button[kind="primary"]{background:#2962ff!important;color:#fff!important;border-color:#2962ff!important;}
.stButton>button:hover{opacity:0.85!important;}
div[data-testid="metric-container"]{background:#1e222d;border:1px solid #2a2e39;border-radius:6px;padding:12px 16px;}
div[data-testid="metric-container"] label{color:#787b86!important;font-size:11px!important;text-transform:uppercase;letter-spacing:0.05em;}
div[data-testid="metric-container"] div[data-testid="stMetricValue"]{font-family:'JetBrains Mono',monospace;font-size:18px!important;color:#d1d4dc!important;}
.stTabs [data-baseweb="tab-list"]{background:#1e222d;border-bottom:1px solid #2a2e39;gap:0;border-radius:6px 6px 0 0;}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:#787b86!important;border-bottom:2px solid transparent!important;font-size:12px!important;padding:9px 18px!important;}
.stTabs [aria-selected="true"]{color:#2962ff!important;border-bottom-color:#2962ff!important;}
.stTabs [data-baseweb="tab-panel"]{background:#131722;padding:0;}
.stDataFrame{background:#1e222d!important;border:1px solid #2a2e39!important;border-radius:6px;}
thead{background:#1a1f2e!important;}
th{color:#787b86!important;font-size:11px!important;text-transform:uppercase;}
td{color:#d1d4dc!important;font-size:12px!important;font-family:'JetBrains Mono',monospace;}
hr{border-color:#2a2e39!important;margin:12px 0;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:#131722;}
::-webkit-scrollbar-thumb{background:#2a2e39;border-radius:2px;}
.sec-header{font-size:11px;font-weight:500;color:#787b86;text-transform:uppercase;letter-spacing:0.07em;padding:6px 0;border-bottom:1px solid #2a2e39;margin-bottom:12px;}
.stat-chip{background:#1e222d;border:1px solid #2a2e39;border-radius:6px;padding:10px 14px;text-align:center;}
.stat-chip .sc-label{font-size:10px;color:#787b86;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;}
.stat-chip .sc-val{font-size:15px;font-weight:500;font-family:'JetBrains Mono',monospace;}
.stAlert{background:#1e222d!important;border:1px solid #2a2e39!important;color:#d1d4dc!important;}
</style>
""", unsafe_allow_html=True)
