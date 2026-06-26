# ─────────────────────────────────────────────
# app.py  —  NFO/BFO Spread Terminal
# streamlit run app.py
# ─────────────────────────────────────────────

import os, base64, hashlib, pyotp, requests, re, time
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date
from urllib.parse import parse_qs, urlparse, unquote
from plotly.subplots import make_subplots
from scipy.stats import norm
from scipy.optimize import brentq
from fyers_apiv3 import fyersModel
import datetime as _dt

# ─── CONFIG ───────────────────────────────────
TOKEN_FILE      = "access_token.txt"
EXPIRY_CACHE_FILE = "expiry_cache.json"
REFRESH_SECONDS = 10

# ─── HELPERS ──────────────────────────────────
def get_secret(key):
    try:
        if key in st.secrets: return str(st.secrets[key])
    except Exception: pass
    return os.environ.get(key, "")

def b64(v): return base64.b64encode(str(v).encode()).decode()

# ─── TOKEN VALIDATION ─────────────────────────
def _is_token_valid(token, client_id):
    """Quick profile call to check if token is still alive."""
    try:
        f = fyersModel.FyersModel(client_id=client_id, token=token, log_path="")
        r = f.get_profile()
        return r and r.get("s") == "ok"
    except Exception:
        return False

# ─── TOTP LOGIN ───────────────────────────────
def generate_token(client_id, secret_key, username, pin, totp_key):
    redirect_uri = "http://127.0.0.1:8080/"
    try:
        s = requests.Session()

        # Step 1
        r1 = s.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                    json={"fy_id": b64(username), "app_id": "2"}, timeout=10)
        if r1.status_code == 429:
            return None, "Rate limited (429). Wait ~60s then Refresh Token."
        r1d = r1.json()
        if not r1d.get("request_key"):
            return None, f"Step 1 failed: {r1d}"

        # Step 2
        r2 = s.post("https://api-t2.fyers.in/vagator/v2/verify_otp",
                    json={"request_key": r1d["request_key"],
                          "otp": pyotp.TOTP(totp_key).now()}, timeout=10)
        r2d = r2.json()
        if not r2d.get("request_key"):
            return None, f"Step 2 failed: {r2d}"

        # Step 3
        r3 = s.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
                    json={"request_key": r2d["request_key"],
                          "identity_type": "pin", "identifier": b64(pin)}, timeout=10)
        r3d = r3.json()
        bearer = (r3d.get("data") or {}).get("access_token")
        if not bearer:
            return None, f"Step 3 failed: {r3d}"

        # Step 4  (allow_redirects=False → 308 with auth_code in Url)
        app_id = client_id.split("-")[0]
        r4 = s.post("https://api-t1.fyers.in/api/v3/token", json={
            "fyers_id": username, "app_id": app_id, "redirect_uri": redirect_uri,
            "appType": "100", "code_challenge": "", "state": "sample_state",
            "scope": "", "nonce": "", "response_type": "code", "create_cookie": True,
        }, headers={"Authorization": f"Bearer {bearer}"},
           allow_redirects=False, timeout=10)
        r4d = r4.json()

        def _is_jwt(s):
            """A JWT is >100 chars and starts with eyJ (base64 of '{"')."""
            return isinstance(s, str) and len(s) > 100 and s.startswith("eyJ")

        def _code_from_url(url):
            if not url: return None
            m = re.search(r'[?&]code=([^&]+)', url)
            if m: return unquote(m.group(1))
            m = re.search(r'auth_code=([^&]+)', url)
            if m: return unquote(m.group(1))
            return None

        data4 = r4d.get("data") or {}

        # ── Case 1: Fyers returned the final access token directly ──
        # It lives in data["auth"] or sometimes data["access_token"]
        for candidate in [
            data4.get("auth"),
            data4.get("access_token"),
            r4d.get("access_token"),
        ]:
            if _is_jwt(candidate):
                return candidate, None

        # ── Case 2: normal auth_code → exchange via SDK ──
        auth_code = (
            r4d.get("code")
            or data4.get("auth_code")
            or _code_from_url(r4d.get("Url", ""))
            or _code_from_url(data4.get("url", ""))
            or _code_from_url(r4d.get("url", ""))
        )

        # ── Case 3: what we got IS a JWT masquerading as auth_code ──
        if _is_jwt(auth_code):
            return auth_code, None

        if not auth_code:
            return None, f"Step 4 failed (status {r4.status_code}): {r4d}"

        # ── Step 5 — SDK exchanges auth_code → access_token ──
        sess = fyersModel.SessionModel(
            client_id=client_id, secret_key=secret_key,
            redirect_uri=redirect_uri,
            response_type="code", grant_type="authorization_code"
        )
        sess.set_token(auth_code)
        r5d = sess.generate_token()
        token = r5d.get("access_token")
        if not token:
            return None, f"Step 5 failed: {r5d} [debug: code_len={len(auth_code)}, code_preview={auth_code[:6]}...{auth_code[-6:]}, client_id={client_id}]"
        return token, None
    except Exception as e:
        return None, f"Exception: {e}"

# ─── CACHED TOKEN (validates before caching) ──
@st.cache_resource
def _cached_token(client_id, secret_key, username, pin, totp_key):
    """
    1. Try file token — but VALIDATE it first.
       If stale → delete file and fall through to fresh login.
    2. Fresh TOTP login.
    Caches the result so the login only runs once per server process.
    """
    try:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
        if token and _is_token_valid(token, client_id):
            return token, None
        # stale — remove so we don't re-use
        try: os.remove(TOKEN_FILE)
        except FileNotFoundError: pass
    except FileNotFoundError:
        pass

    token, err = generate_token(client_id, secret_key, username, pin, totp_key)
    if token:
        try:
            with open(TOKEN_FILE, "w") as f: f.write(token)
        except Exception: pass
        return token, None
    return None, err

def get_shared_token():
    cid  = get_secret("FYERS_CLIENT_ID")
    sec  = get_secret("FYERS_SECRET_KEY")
    usr  = get_secret("FYERS_USERNAME")
    pin  = get_secret("FYERS_PIN")
    totp = get_secret("FYERS_TOTP_KEY")
    miss = [k for k,v in {"FYERS_CLIENT_ID":cid,"FYERS_SECRET_KEY":sec,
                           "FYERS_USERNAME":usr,"FYERS_PIN":pin,
                           "FYERS_TOTP_KEY":totp}.items() if not v]
    if miss: return None, f"Missing credentials: {', '.join(miss)}"
    return _cached_token(cid, sec, usr, pin, totp)

def get_fyers():
    token, err = get_shared_token()
    if not token:
        st.error(f"❌ Login failed: {err}")
        return None
    return fyersModel.FyersModel(
        client_id=get_secret("FYERS_CLIENT_ID"), token=token, log_path="")

# ─── EXPIRY CACHE ─────────────────────────────
_UNDERLYING_SYM = {
    "SENSEX":"BSE:SENSEX-INDEX","BANKEX":"BSE:BANKEX-INDEX",
    "NIFTY":"NSE:NIFTY50-INDEX","BANKNIFTY":"NSE:NIFTYBANK-INDEX",
    "FINNIFTY":"NSE:FINNIFTY-INDEX","MIDCPNIFTY":"NSE:MIDCPNIFTY-INDEX",
}
_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]

def _load_expiry_cache():
    try:
        import json
        with open(EXPIRY_CACHE_FILE) as f: data = json.load(f)
        if data.get("date") == date.today().isoformat():
            return data.get("expiries", {})
    except Exception: pass
    return {}

def _save_expiry_cache(expiries):
    import json
    try:
        with open(EXPIRY_CACHE_FILE, "w") as f:
            json.dump({"date": date.today().isoformat(), "expiries": expiries}, f)
    except Exception: pass

def _fetch_expiries(fyers_sym):
    from collections import defaultdict
    token, err = get_shared_token()
    if not token: return {}, f"No token: {err}"
    cid = get_secret("FYERS_CLIENT_ID")
    fyers = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
    resp = fyers.optionchain(data={"symbol":fyers_sym,"strikecount":1,"timestamp":""})
    if not (resp and resp.get("s")=="ok"):
        return {}, f"optionchain API returned: {resp}"
    raw = resp.get("data",{}).get("expiryData",[])
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict): continue
        try:
            dd,mm,yyyy = map(int, entry.get("date","").split("-"))
            parsed.append((yyyy%100, mm, dd, _MONTHS[mm-1]))
        except Exception: continue
    by_month = defaultdict(list)
    for yy,mm,dd,mon in parsed: by_month[(yy,mm)].append(dd)
    last_of_month = {k:max(v) for k,v in by_month.items()}
    result = {}
    for yy,mm,dd,mon in parsed:
        is_monthly = (dd == last_of_month[(yy,mm)])
        if is_monthly:
            result[f"{dd:02d} {mon} {yy:02d} (M)"] = f"{yy:02d}{mon}"
        else:
            result[f"{dd:02d} {mon} {yy:02d} (W)"] = f"{yy:02d}{mm:02d}{dd:02d}"
    return result, None

def get_expiries_for(exchange, underlying):
    sym = _UNDERLYING_SYM.get(underlying.upper(), f"{exchange}:{underlying}-INDEX")
    cached = _load_expiry_cache()
    if cached.get(sym): return cached[sym]
    result, err = _fetch_expiries(sym)
    if result:
        cached[sym] = result
        _save_expiry_cache(cached)
    else:
        st.warning(f"⚠️ Expiry fetch failed for `{sym}`: {err}")
    return result

def expiry_selectbox(label, opts, manual_key, select_key, default):
    if opts:
        codes = list(opts.values())
        lmap  = {v:k for k,v in opts.items()}
        return st.selectbox(label, codes, format_func=lambda c:lmap.get(c,c), key=select_key)
    return st.text_input(label, value=default, key=manual_key)

# ─── SYMBOL BUILDER ───────────────────────────
def build_symbol(exchange, underlying, expiry, opt_type, strike):
    """
    Monthly : YYMON  e.g. 26JUN   → BSE:SENSEX26JUN80000CE
    Weekly  : YYMMDD e.g. 260612  → BSE:SENSEX26612 80000CE
                                      (MM drops leading zero: 06→6)
    """
    ot     = "CE" if str(opt_type).upper() in ("C","CE") else "PE"
    expiry = str(expiry).strip().upper()
    strike = int(strike)

    if any(c.isalpha() for c in expiry):
        # monthly
        return f"{exchange}:{underlying}{expiry}{strike}{ot}"

    # weekly YYMMDD (exactly 6 digits)
    if len(expiry) == 6 and expiry.isdigit():
        yy = expiry[0:2]
        mm = str(int(expiry[2:4]))   # "06" → "6"
        dd = expiry[4:6]
        return f"{exchange}:{underlying}{yy}{mm}{dd}{strike}{ot}"

    # fallback
    return f"{exchange}:{underlying}{expiry}{strike}{ot}"

# ─── FETCH CANDLES ────────────────────────────
def fetch_candles(fyers, symbol, interval, date_str):
    r = fyers.history(data={"symbol":symbol,"resolution":str(interval),
                             "date_format":"1","range_from":date_str,
                             "range_to":date_str,"cont_flag":"1"})
    if r.get("s") != "ok": return pd.DataFrame()
    df = pd.DataFrame(r["candles"], columns=["ts","open","high","low","close","vol"])
    df["datetime"] = (pd.to_datetime(df["ts"],unit="s")
                        .dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata")
                        .dt.tz_localize(None))
    return df.set_index("datetime").drop(columns=["ts"])

# ─── PAGE CONFIG & CSS ────────────────────────
st.set_page_config(page_title="NFO/BFO Spread Terminal",
                   page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")

T = {"bg":"#f0f4f8","bg2":"#ffffff","card":"#ffffff","card_bdr":"#cbd5e1",
     "text":"#0f172a","text2":"#475569","text3":"#94a3b8",
     "ce":"#dc2626","pe":"#059669","diff":"#d97706","accent":"#0284c7",
     "divider":"#e2e8f0","plot_bg":"#f8fafc","grid":"#e2e8f0"}

st.markdown(f"""
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  *{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important}}
  code{{font-family:"Courier New",monospace!important}}
  .stApp{{background:{T['bg']}!important;color:{T['text']}!important}}
  section[data-testid="stSidebar"]{{background:#e8edf5!important;border-right:1px solid {T['card_bdr']}!important}}
  .top-nav{{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;background:{T['bg2']};border-bottom:1px solid {T['card_bdr']};border-radius:12px;margin-bottom:20px}}
  .nav-logo{{width:36px;height:36px;background:linear-gradient(135deg,{T['ce']},{T['accent']});border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px}}
  .nav-title{{font-family:"Syne",sans-serif!important;font-size:18px;font-weight:800;color:{T['text']}}}
  .nav-subtitle{{font-size:11px;color:{T['text3']};font-family:"Space Mono",monospace!important}}
  .pill{{padding:5px 12px;border-radius:20px;font-size:11px;font-weight:600}}
  .pill-live{{background:rgba(52,211,153,.15);color:{T['pe']};border:1px solid rgba(52,211,153,.3);animation:pulse 2s infinite}}
  .pill-time{{background:{T['card']};color:{T['text2']};border:1px solid {T['card_bdr']};font-family:"Space Mono",monospace!important}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
  .metrics-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}}
  .metric-card{{background:{T['card']};border:1px solid {T['card_bdr']};border-radius:12px;padding:18px 20px;position:relative;overflow:hidden;transition:transform .15s,box-shadow .15s}}
  .metric-card:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}}
  .metric-card::before{{content:"";position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0}}
  .card-ce::before{{background:{T['ce']}}}.card-pe::before{{background:{T['pe']}}}
  .card-diff::before{{background:{T['diff']}}}.card-time::before{{background:{T['accent']}}}
  .metric-label{{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{T['text3']};margin-bottom:10px}}
  .metric-value{{font-family:"Space Mono",monospace!important;font-size:28px;font-weight:700;line-height:1;margin-bottom:8px}}
  .val-ce{{color:{T['ce']}}}.val-pe{{color:{T['pe']}}}.val-diff{{color:{T['diff']}}}
  .val-time{{color:{T['accent']};font-size:22px}}
  .metric-sub{{font-size:10px;color:{T['text3']};font-family:"Space Mono",monospace!important}}
  .metric-badge{{position:absolute;top:14px;right:14px;font-size:18px;opacity:.4}}
  hr{{border-color:{T['divider']}!important}}
  div[data-testid="stVerticalBlock"]>div{{gap:0rem!important}}
  .stSelectbox,.stTextInput,.stNumberInput{{margin-bottom:-18px!important}}
  .stSelectbox div[data-baseweb="select"]>div,.stTextInput input,.stNumberInput input{{font-size:13px!important}}
  .stSelectbox label,.stTextInput label,.stNumberInput label{{font-size:12px!important}}
  button[data-testid="collapsedControl"]{{display:none!important}}
  .block-container{{padding-top:.5rem!important}}
  header[data-testid="stHeader"]{{background:transparent!important;height:0!important;min-height:0!important}}
  header[data-testid="stHeader"]>*{{display:none!important}}
  div[data-testid="stDecoration"]{{display:none}}
</style>""", unsafe_allow_html=True)

# ─── DATE ─────────────────────────────────────
today = date.today()
default_date = (today - pd.Timedelta(days=1) if today.weekday()==5 else
                today - pd.Timedelta(days=2) if today.weekday()==6 else today)
_now = _dt.datetime.now().strftime("%H:%M:%S")

# ─── REFRESH TOKEN BUTTON ─────────────────────
if st.button("🔄 Refresh Token", key="rtok"):
    _cached_token.clear()
    for f in [TOKEN_FILE, EXPIRY_CACHE_FILE]:
        try: os.remove(f)
        except FileNotFoundError: pass
    st.rerun()

# ─── AUTH CHECK ───────────────────────────────
_tok, _tok_err = get_shared_token()
if not _tok:
    if _tok_err and "Missing" in _tok_err:
        st.error(f"❌ **Credentials not configured.**\n\n{_tok_err}\n\n"
                 "Add to Streamlit Secrets:\n```\n"
                 "FYERS_CLIENT_ID = \"XXXX-100\"\n"
                 "FYERS_SECRET_KEY = \"...\"\n"
                 "FYERS_USERNAME = \"...\"\n"
                 "FYERS_PIN = \"...\"\n"
                 "FYERS_TOTP_KEY = \"...\"\n```")
    elif _tok_err and "429" in _tok_err:
        st.error("❌ Rate limited. Wait ~60s then click **Refresh Token**.")
    else:
        st.error(f"❌ Login failed: {_tok_err}")
    st.stop()

# ─── TOP NAV ──────────────────────────────────
st.markdown(f"""
<div class="top-nav">
  <div style="display:flex;align-items:center;gap:12px">
    <div class="nav-logo">📊</div>
    <div>
      <div class="nav-title">NFO / BFO Spread Terminal</div>
      <div class="nav-subtitle">NFO / BFO Options Spread</div>
    </div>
  </div>
  <div style="display:flex;gap:8px;align-items:center">
    <span class="pill pill-live">● LIVE</span>
    <span class="pill pill-time">{_now} IST</span>
  </div>
</div>""", unsafe_allow_html=True)

# fix Refresh Token button position
st.markdown("""<style>
div[data-testid="stMainBlockContainer"]>div>div>div:nth-child(1) button{
  position:fixed!important;top:10px!important;right:200px!important;
  z-index:9999!important;background:rgba(2,132,199,.15)!important;
  border:1px solid rgba(2,132,199,.4)!important;color:#0284c7!important;
  border-radius:20px!important;padding:3px 12px!important;
  font-size:11px!important;font-weight:600!important}
</style>""", unsafe_allow_html=True)

# ─── SESSION STATE ────────────────────────────
for k in ["df","df_custom"]:
    if k not in st.session_state:
        st.session_state[k] = pd.DataFrame()

# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Spread Dashboard","🧮 Butterfly","📐 IV Analysis"])

# ═════════════════════════════════════════════
# TAB 2 — BUTTERFLY
# ═════════════════════════════════════════════
with tab2:
    st.markdown("<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:8px;'>Configure 4 Legs</div>", unsafe_allow_html=True)
    UNDERLYINGS=["SENSEX","BANKEX","NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"]
    leg_colors=["#f87171","#34d399","#60a5fa","#fbbf24"]
    leg_labels=["Leg 1","Leg 2","Leg 3","Leg 4"]
    leg_configs=[]

    def next_wd(wd):
        d=date.today(); ahead=wd-d.weekday()
        if ahead<=0: ahead+=7
        return (d+pd.Timedelta(days=ahead)).strftime("%y%m%d")

    bse_exp=next_wd(3); nse_exp=next_wd(1)
    LEG_DEFAULTS=[("BSE","SENSEX",bse_exp,80000,"CE",1.0),
                  ("NSE","NIFTY", nse_exp,24200,"CE",3.3),
                  ("BSE","SENSEX",bse_exp,80000,"CE",1.0),
                  ("NSE","NIFTY", nse_exp,24200,"CE",3.3)]

    if "c_init" not in st.session_state:
        for i,(ex,un,ep,st_,ot,mu) in enumerate(LEG_DEFAULTS):
            st.session_state[f"c_exch_{i}"]=ex
            st.session_state[f"c_under_{i}"]=un
            st.session_state[f"c_str_{i}"]=float(st_)
            st.session_state[f"c_opt_{i}"]=ot
            st.session_state[f"c_lots_{i}"]=mu
        st.session_state["c_init"]=True

    crow=st.columns([1.2,1,1,1,1.5])
    with crow[0]: cdate=st.date_input("Date",value=default_date,key="c_date")
    with crow[1]: cint =st.selectbox("Interval",[1,3,5,10,15,30,60],index=2,key="c_int")
    with crow[2]: cauto=st.checkbox("Auto Refresh",value=False,key="c_auto")
    with crow[3]: csec =st.slider("Sec",5,60,10,key="c_sec")
    with crow[4]: cfetch=st.button("⟳  FETCH 4-LEG DATA",type="primary",
                                    use_container_width=True,key="c_fetch")

    for ri in range(2):
        li=[ri*2,ri*2+1]
        cols=st.columns([.25,.5,.8,.8,.65,.65,.6,.15,.25,.5,.8,.8,.65,.65,.6])
        for j,i in enumerate(li):
            d_ex,d_un,d_ep,d_st,d_ot,d_mu=LEG_DEFAULTS[i]
            off=j*8
            cols[off].markdown(f"<div style='padding-top:28px;font-size:10px;font-weight:700;color:{leg_colors[i]};'>{leg_labels[i].upper()}</div>",unsafe_allow_html=True)
            with cols[off+1]: exch =st.selectbox("Exchange",["BSE","NSE"] if d_ex=="BSE" else ["NSE","BSE"],key=f"c_exch_{i}")
            with cols[off+2]: under=st.selectbox("Underlying",[d_un]+[u for u in UNDERLYINGS if u!=d_un],key=f"c_under_{i}")
            _opts=get_expiries_for(exch,under)
            with cols[off+3]: expiry=expiry_selectbox("Expiry",_opts,f"c_em_{i}",f"c_es_{i}",d_ep)
            with cols[off+4]: strike=st.number_input("Strike",step=100,key=f"c_str_{i}")
            with cols[off+5]: otype =st.selectbox("CE/PE",["CE","PE"],key=f"c_opt_{i}")
            with cols[off+6]: mult  =st.number_input("Mult",min_value=0.1,step=0.1,key=f"c_lots_{i}")
            if j==0: cols[7].markdown("<div style='padding-top:28px;font-size:10px;color:#e2e8f0;text-align:center;'>│</div>",unsafe_allow_html=True)
            leg_configs.append({"exchange":exch,"underlying":under,"expiry":expiry,
                                 "strike":int(strike),"opt_type":otype,"lots":mult})

    cdate_str=cdate.strftime("%Y-%m-%d")
    L=leg_configs
    def lname(i): return f"{L[i]['lots']}×{L[i]['underlying']} {L[i]['opt_type']}"
    st.markdown(f"<div style='font-size:11px;color:#64748b;margin:4px 0 8px 0;font-family:monospace;'>Chart 1:&nbsp;<span style='color:#f87171'>{lname(0)}</span>−<span style='color:#34d399'>{lname(1)}</span>&nbsp;|&nbsp;<span style='color:#60a5fa'>{lname(2)}</span>−<span style='color:#fbbf24'>{lname(3)}</span>&nbsp;&nbsp;Chart 2:&nbsp;(L1−L2)+(L3−L4)</div>",unsafe_allow_html=True)

    if cfetch:
        fyers=get_fyers()
        if fyers:
            raw=[];ok=True
            with st.spinner("Fetching..."):
                for i,leg in enumerate(leg_configs):
                    sym=build_symbol(leg["exchange"],leg["underlying"],
                                     leg["expiry"],leg["opt_type"][0],leg["strike"])
                    df_=fetch_candles(fyers,sym,cint,cdate_str)
                    if df_.empty:
                        st.warning(f"⚠️ {leg_labels[i]}: No data — `{sym}`")
                        ok=False;break
                    raw.append(df_[~df_.index.duplicated(keep="last")]["close"]*leg["lots"])
            if ok and len(raw)==4:
                idx=raw[0].index
                s=[r.reindex(idx,method="ffill").fillna(0) for r in raw]
                st.session_state.df_custom=pd.DataFrame(
                    {"spread12":s[0]-s[1],"spread34":s[2]-s[3],
                     "combined":(s[0]-s[1])+(s[2]-s[3])})

    dfc=st.session_state.df_custom
    if not dfc.empty:
        def darrow(v):
            return f"<span style='color:{'#f87171' if v>=0 else '#34d399'};font-size:11px;'>{'▲' if v>=0 else '▼'} {abs(v):.2f}</span>"
        v12=dfc['spread12'].iloc[-1]; v34=dfc['spread34'].iloc[-1]; vc=dfc['combined'].iloc[-1]
        d12=v12-dfc['spread12'].iloc[-2] if len(dfc)>1 else 0
        d34=v34-dfc['spread34'].iloc[-2] if len(dfc)>1 else 0
        dc =vc -dfc['combined'].iloc[-2]  if len(dfc)>1 else 0
        upd=dfc.index[-1].strftime("%H:%M:%S")
        st.markdown(f"""<div class="metrics-grid">
          <div class="metric-card card-ce"><div class="metric-badge">📊</div><div class="metric-label">LEG 1 − LEG 2</div><div class="metric-value val-ce">{v12:+.1f}</div><div class="metric-sub">Spread {darrow(d12)}</div></div>
          <div class="metric-card card-pe"><div class="metric-badge">📊</div><div class="metric-label">LEG 3 − LEG 4</div><div class="metric-value val-pe">{v34:+.1f}</div><div class="metric-sub">Spread {darrow(d34)}</div></div>
          <div class="metric-card card-diff"><div class="metric-badge">⚖️</div><div class="metric-label">4 LEG TOTAL</div><div class="metric-value val-diff">{vc:+.1f}</div><div class="metric-sub">(L1−L2)+(L3−L4) {darrow(dc)}</div></div>
          <div class="metric-card card-time"><div class="metric-badge">🕐</div><div class="metric-label">LAST UPDATE</div><div class="metric-value val-time">{upd}</div><div class="metric-sub">{len(dfc)} candles</div></div>
        </div>""",unsafe_allow_html=True)

        def hlines(fig,s,c):
            fig.add_hline(y=0,line_dash="dash",line_color="#444")
            for y,lbl in [(s.max(),"H"),(s.min(),"L")]:
                fig.add_hline(y=y,line_dash="dot",line_color=c,line_width=1,
                    annotation_text=f"{lbl}: {y:.0f}",annotation_position="right",
                    annotation_font=dict(color=c,size=10))

        def clayout(fig,title,h=380):
            fig.update_layout(title=dict(text=title,font=dict(size=12,color=T["text2"]),x=0),
                height=h,plot_bgcolor=T["plot_bg"],paper_bgcolor=T["plot_bg"],
                font=dict(color=T["text2"]),hovermode="x unified",
                margin=dict(l=10,r=10,t=40,b=10),
                legend=dict(bgcolor=T["card"],bordercolor=T["card_bdr"],borderwidth=1,
                    orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                xaxis=dict(gridcolor=T["grid"],tickfont=dict(size=10),showspikes=True,spikemode="across",spikecolor=T["text3"],spikethickness=1),
                yaxis=dict(gridcolor=T["grid"],title="Value (₹)",tickfont=dict(size=10),showspikes=True,spikemode="across",spikecolor=T["text3"],spikethickness=1),
                hoverlabel=dict(bgcolor=T["card"],bordercolor=T["card_bdr"],font=dict(color=T["text"])))

        f1=go.Figure()
        f1.add_trace(go.Scatter(x=dfc.index,y=dfc["spread12"],name="Leg1−Leg2",line=dict(color="#f87171",width=2),hovertemplate="%{x|%H:%M}<br>%{y:.2f}<extra></extra>"))
        f1.add_trace(go.Scatter(x=dfc.index,y=dfc["spread34"],name="Leg3−Leg4",line=dict(color="#60a5fa",width=2),hovertemplate="%{x|%H:%M}<br>%{y:.2f}<extra></extra>"))
        hlines(f1,dfc["spread12"],"#f87171"); clayout(f1,"Spread Chart — Leg1−Leg2 & Leg3−Leg4")
        st.plotly_chart(f1,use_container_width=True)

        f2=go.Figure()
        f2.add_trace(go.Scatter(x=dfc.index,y=dfc["combined"],name="Combined",line=dict(color="#818cf8",width=2.5),fill="tozeroy",fillcolor="rgba(129,140,248,.08)",hovertemplate="%{x|%H:%M}<br>%{y:.2f}<extra></extra>"))
        hlines(f2,dfc["combined"],"#818cf8"); clayout(f2,"Combined Chart — (Leg1−Leg2)+(Leg3−Leg4)")
        st.plotly_chart(f2,use_container_width=True)

        if cauto and cdate_str==date.today().strftime("%Y-%m-%d"):
            time.sleep(csec); st.rerun()
    else:
        st.info("👆 Configure your 4 legs above and click **Fetch 4-Leg Data**.")

# ═════════════════════════════════════════════
# TAB 1 — SPREAD DASHBOARD
# ═════════════════════════════════════════════
with tab1:
    st.markdown("<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:4px;'>⚙ Settings</div>",unsafe_allow_html=True)
    r0=st.columns([1.2,1,1,1,1,1,1,1.5])
    with r0[0]: sel_date =st.date_input("Date",value=default_date,key="date_inp")
    with r0[1]: mult     =st.number_input("Ratio",value=3.3,step=0.1,min_value=0.1,key="mult")
    with r0[2]: cint1    =st.selectbox("Interval (min)",[1,3,5,10,15,30,60],index=2,key="interval")
    with r0[3]: show_diff=st.checkbox("4-Leg Chart",value=True,key="show_diff")
    with r0[4]: auto_ref =st.checkbox("Auto Refresh",value=True,key="auto_ref")
    with r0[5]: ref_sec  =st.slider("Refresh (sec)",5,60,REFRESH_SECONDS,key="ref_sec")
    with r0[6]: st.markdown("<div style='height:28px'></div>",unsafe_allow_html=True)
    with r0[7]: fetch_btn=st.button("⟳  FETCH DATA",use_container_width=True,type="primary",key="fetch_btn")

    date_str=sel_date.strftime("%Y-%m-%d")

    lr=st.columns([.25,.5,.8,.8,.8,.65,.65,.15,.25,.5,.8,.8,.8,.65,.65])
    lr[0].markdown("<div style='padding-top:28px;font-size:10px;font-weight:700;color:#dc2626;'>LEG 1</div>",unsafe_allow_html=True)
    with lr[1]:  sx_exch =st.selectbox("Exchange",["BSE","NSE"],index=0,key="sx_exch")
    with lr[2]:  sx_under=st.selectbox("Underlying",["SENSEX","BANKEX","NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"],index=0,key="sx_under")
    _sx=get_expiries_for(sx_exch,sx_under)
    with lr[3]:  sx_ce_exp=expiry_selectbox("CE Expiry",_sx,"sx_ce_m","sx_ce_s","260612")
    with lr[4]:  sx_pe_exp=expiry_selectbox("PE Expiry",_sx,"sx_pe_m","sx_pe_s","260612")
    with lr[5]:  sx_ce_str=st.number_input("CE Strike",value=80000,step=100,key="sx_ce_str")
    with lr[6]:  sx_pe_str=st.number_input("PE Strike",value=80000,step=100,key="sx_pe_str")
    lr[7].markdown("<div style='padding-top:28px;font-size:10px;color:#e2e8f0;text-align:center;'>│</div>",unsafe_allow_html=True)
    lr[8].markdown("<div style='padding-top:28px;font-size:10px;font-weight:700;color:#0284c7;'>LEG 2</div>",unsafe_allow_html=True)
    with lr[9]:  nf_exch =st.selectbox("Exchange",["NSE","BSE"],index=0,key="nf_exch")
    with lr[10]: nf_under=st.selectbox("Underlying",["NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","SENSEX","BANKEX"],index=0,key="nf_under")
    _nf=get_expiries_for(nf_exch,nf_under)
    with lr[11]: nf_ce_exp=expiry_selectbox("CE Expiry",_nf,"nf_ce_m","nf_ce_s","260610")
    with lr[12]: nf_pe_exp=expiry_selectbox("PE Expiry",_nf,"nf_pe_m","nf_pe_s","260610")
    with lr[13]: nf_ce_str=st.number_input("CE Strike",value=24800,step=50,key="nf_ce_str")
    with lr[14]: nf_pe_str=st.number_input("PE Strike",value=24800,step=50,key="nf_pe_str")

    st.divider()

    sym_sx_ce=build_symbol(sx_exch,sx_under,sx_ce_exp,"C",int(sx_ce_str))
    sym_sx_pe=build_symbol(sx_exch,sx_under,sx_pe_exp,"P",int(sx_pe_str))
    sym_nf_ce=build_symbol(nf_exch,nf_under,nf_ce_exp,"C",int(nf_ce_str))
    sym_nf_pe=build_symbol(nf_exch,nf_under,nf_pe_exp,"P",int(nf_pe_str))

    def fetch_live():
        fyers=get_fyers()
        if not fyers: return pd.DataFrame()
        with st.spinner("Fetching..."):
            dsc=fetch_candles(fyers,sym_sx_ce,cint1,date_str)
            dsp=fetch_candles(fyers,sym_sx_pe,cint1,date_str)
            dnc=fetch_candles(fyers,sym_nf_ce,cint1,date_str)
            dnp=fetch_candles(fyers,sym_nf_pe,cint1,date_str)
            dss=fetch_candles(fyers,"BSE:SENSEX-INDEX",cint1,date_str)
            if dss.empty: dss=fetch_candles(fyers,"BSE:SENSEX",cint1,date_str)
            dns=fetch_candles(fyers,"NSE:NIFTY50-INDEX",cint1,date_str)
            if dns.empty: dns=fetch_candles(fyers,"NSE:NIFTY50",cint1,date_str)
        if any(d.empty for d in [dsc,dsp,dnc,dnp]):
            st.warning(f"⚠️ No data. Symbols: `{sym_sx_ce}` | `{sym_sx_pe}` | `{sym_nf_ce}` | `{sym_nf_pe}`")
            return pd.DataFrame()
        for d in [dsc,dsp,dnc,dnp,dss,dns]:
            d.drop(index=d.index[d.index.duplicated(keep="last")],inplace=True,errors="ignore")
        idx=dsc.index.intersection(dsp.index).intersection(dnc.index).intersection(dnp.index)
        df=pd.DataFrame({"sensex_ce":dsc["close"].reindex(idx),"sensex_pe":dsp["close"].reindex(idx),
                          "nifty_ce":dnc["close"].reindex(idx),"nifty_pe":dnp["close"].reindex(idx)}).dropna()
        if not dss.empty and not dns.empty:
            df["sx_spot"]=dss["close"].reindex(df.index,method="ffill")
            df["nf_spot"]=dns["close"].reindex(df.index,method="ffill")
            df["synth_sx"]=df["sx_spot"]+df["sensex_ce"]-df["sensex_pe"]
            df["synth_nf"]=df["nf_spot"]+df["nifty_ce"] -df["nifty_pe"]
            df["synth_ratio"]=df["synth_sx"]/df["synth_nf"]
        df["ce_spread"]=df["sensex_ce"]-(df["nifty_ce"]*mult)
        df["pe_spread"]=df["sensex_pe"]-(df["nifty_pe"]*mult)
        df["diff"]=df["ce_spread"]+df["pe_spread"]
        return df

    if fetch_btn or st.session_state.df.empty:
        st.session_state.df=fetch_live()
    df=st.session_state.df

    if df.empty:
        st.info("👆 Set your options above and click **Fetch Data**.")
    else:
        lat=df.iloc[-1]
        cev=lat["ce_spread"]; pev=lat["pe_spread"]; dv=lat["diff"]
        upd=df.index[-1].strftime("%H:%M:%S")
        is_today=date_str==date.today().strftime("%Y-%m-%d")
        ced=cev-df["ce_spread"].iloc[-2] if len(df)>1 else 0
        ped=pev-df["pe_spread"].iloc[-2] if len(df)>1 else 0
        dd2=dv -df["diff"].iloc[-2]       if len(df)>1 else 0
        def dh(v):
            return f"<span style='color:{'#f87171' if v>=0 else '#34d399'};font-size:11px;font-family:Space Mono'>{'▲' if v>=0 else '▼'} {abs(v):.2f}</span>"
        sv=f"{lat['synth_ratio']:.4f}" if "synth_ratio" in df.columns and pd.notna(lat.get("synth_ratio")) else "N/A"
        st.markdown(f"""<div class="metrics-grid">
          <div class="metric-card card-ce"><div class="metric-badge">📈</div><div class="metric-label">CE SPREAD</div><div class="metric-value val-ce">{cev:+.1f}</div><div class="metric-sub">{sx_under} CE − {nf_under} CE ×{mult} &nbsp;{dh(ced)}</div></div>
          <div class="metric-card card-pe"><div class="metric-badge">📉</div><div class="metric-label">PE SPREAD</div><div class="metric-value val-pe">{pev:+.1f}</div><div class="metric-sub">{sx_under} PE − {nf_under} PE ×{mult} &nbsp;{dh(ped)}</div></div>
          <div class="metric-card card-diff"><div class="metric-badge">⚖️</div><div class="metric-label">4 LEG TOTAL</div><div class="metric-value val-diff">{dv:+.1f}</div><div class="metric-sub">CE+PE combined &nbsp;{dh(dd2)}</div></div>
          <div class="metric-card card-time"><div class="metric-badge">🔢</div><div class="metric-label">SYNTHETIC MULTIPLIER</div><div class="metric-value val-time">{sv}</div><div class="metric-sub">{'LIVE' if is_today else 'HIST'} · {upd}</div></div>
        </div>""",unsafe_allow_html=True)

        has_synth="synth_ratio" in df.columns and df["synth_ratio"].notna().any()
        nr=1+int(show_diff)+int(has_synth)
        rh=([.55,.25,.20] if nr==3 else [.70,.30] if nr==2 else [1.0])
        fig=make_subplots(rows=nr,cols=1,shared_xaxes=True,row_heights=rh,vertical_spacing=.04)
        dr=2 if show_diff else None
        sr=(3 if show_diff else 2) if has_synth else None
        fig.add_trace(go.Scatter(x=df.index,y=df["ce_spread"],name="CE Spread",line=dict(color="#ff4444",width=2),hovertemplate="%{x|%H:%M}<br>CE: %{y:.2f}<extra></extra>"),row=1,col=1)
        fig.add_trace(go.Scatter(x=df.index,y=df["pe_spread"],name="PE Spread",line=dict(color="#44ff88",width=2),hovertemplate="%{x|%H:%M}<br>PE: %{y:.2f}<extra></extra>"),row=1,col=1)
        fig.add_hline(y=0,line_dash="dash",line_color="#444",row=1,col=1)
        if show_diff:
            fig.add_trace(go.Scatter(x=df.index,y=df["diff"],name="4 Leg",line=dict(color="#ffaa00",width=2),hovertemplate="%{x|%H:%M}<br>4Leg: %{y:.2f}<extra></extra>"),row=dr,col=1)
            fig.add_hline(y=0,line_dash="dash",line_color="#444",row=dr,col=1)
            for y,lbl in[(df["diff"].max(),"H"),(df["diff"].min(),"L")]:
                fig.add_hline(y=y,line_dash="dot",line_color="#ffaa00",line_width=1,opacity=.5,
                    annotation_text=f"{lbl}: {y:.0f}",annotation_position="right",
                    annotation_font=dict(color="#ffaa00",size=10),row=dr,col=1)
        if has_synth:
            fig.add_trace(go.Scatter(x=df.index,y=df["synth_ratio"],name="Synth Ratio",line=dict(color="#818cf8",width=2),hovertemplate="%{x|%H:%M}<br>Synth: %{y:.4f}<extra></extra>"),row=sr,col=1)
            for y,lbl in[(df["synth_ratio"].max(),"H"),(df["synth_ratio"].min(),"L")]:
                fig.add_hline(y=y,line_dash="dot",line_color="#818cf8",line_width=1,opacity=.5,
                    annotation_text=f"{lbl}: {y:.4f}",annotation_position="right",
                    annotation_font=dict(color="#818cf8",size=10),row=sr,col=1)
        fig.update_layout(height=580+(120 if has_synth else 0),
            plot_bgcolor=T["plot_bg"],paper_bgcolor=T["plot_bg"],
            font=dict(color=T["text2"],family="Space Mono"),hovermode="x unified",
            margin=dict(l=10,r=10,t=10,b=10),
            legend=dict(bgcolor=T["card"],bordercolor=T["card_bdr"],borderwidth=1,
                font=dict(size=11),orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
            xaxis=dict(gridcolor=T["grid"],tickfont=dict(size=10)),
            yaxis=dict(gridcolor=T["grid"],title="Spread (₹)",tickfont=dict(size=10)),
            hoverlabel=dict(bgcolor=T["card"],bordercolor=T["card_bdr"],font=dict(color=T["text"])))
        if show_diff:
            fig.update_yaxes(gridcolor=T["grid"],title_text="4 Leg",tickfont=dict(size=10),row=dr,col=1)
        if has_synth:
            fig.update_yaxes(gridcolor=T["grid"],title_text="Synth Ratio",tickfont=dict(size=10),row=sr,col=1)
        st.plotly_chart(fig,use_container_width=True)

# ═════════════════════════════════════════════
# TAB 3 — IV ANALYSIS
# ═════════════════════════════════════════════
with tab3:
    SX_LOT=20; NF_LOT=65
    def bs_price(S,K,T,r,sigma,opt):
        import math
        if T<=0 or sigma<=0: return max(0.,S-K) if opt=="CE" else max(0.,K-S)
        d1=(math.log(S/K)+(r+.5*sigma**2)*T)/(sigma*math.sqrt(T)); d2=d1-sigma*math.sqrt(T)
        return (S*norm.cdf(d1)-K*math.exp(-r*T)*norm.cdf(d2) if opt=="CE"
                else K*math.exp(-r*T)*norm.cdf(-d2)-S*norm.cdf(-d1))
    def calc_iv(p,S,K,T,r,opt):
        if T<=0 or S<=0 or K<=0 or p<=0: return float("nan")
        try: return brentq(lambda s:bs_price(S,K,T,r,s,opt)-p,1e-6,20.,xtol=1e-6,maxiter=200)*100
        except: return float("nan")
    def exp2date(s):
        import calendar as _c
        s=s.strip().upper()
        MO={m:i+1 for i,m in enumerate(["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"])}
        if any(c.isalpha() for c in s):
            yy=int(s[:2]); mo=s[2:5]; mm=MO.get(mo,3)
            return date(2000+yy,mm,_c.monthrange(2000+yy,mm)[1])
        if len(s)==5: return date(2000+int(s[0:2]),int(s[2]),int(s[3:5]))
        return date(2000+int(s[0:2]),int(s[2:4]),int(s[4:6]))
    def rnd(v,b): return int(b*round(float(v)/b))

    st.markdown("<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#64748b;margin-bottom:4px;'>⚙ IV Settings</div>",unsafe_allow_html=True)
    ivr=st.columns([1.2,1,1,1,1,1,1,1.5])
    with ivr[0]: iv_date=st.date_input("Date",value=default_date,key="iv_date")
    with ivr[1]: iv_int =st.selectbox("Interval (min)",[1,3,5,10,15,30,60],index=2,key="iv_int")
    _ivsx=get_expiries_for("BSE","SENSEX"); _ivnf=get_expiries_for("NSE","NIFTY")
    with ivr[2]: sx_exp=expiry_selectbox("Sensex Expiry",_ivsx,"iv_sx_m","iv_sx_s","260612")
    with ivr[3]: nf_exp=expiry_selectbox("Nifty Expiry", _ivnf,"iv_nf_m","iv_nf_s","260610")
    with ivr[4]: iv_rfr=st.number_input("Risk-Free %",value=6.5,step=0.1,key="iv_rfr")
    with ivr[5]: iv_auto=st.checkbox("Auto Refresh",value=True,key="iv_auto")
    with ivr[6]: iv_sec =st.slider("Refresh (sec)",5,60,15,key="iv_sec")
    with ivr[7]: iv_fetch=st.button("⟳  FETCH IV DATA",type="primary",use_container_width=True,key="iv_fetch")

    iv_ds=iv_date.strftime("%Y-%m-%d")
    ivm=st.session_state.get("iv_mult")
    st.markdown(f"<div style='font-size:11px;color:#64748b;margin:2px 0 8px 0;'>Synthetic Multiplier: {'<b>'+str(round(ivm,4))+'</b>' if ivm else '<i>fetched on load</i>'} &nbsp;|&nbsp; Sensex lot: <b>{SX_LOT}</b> &nbsp;|&nbsp; Nifty lot: <b>{NF_LOT}</b></div>",unsafe_allow_html=True)

    if iv_fetch or st.session_state.pop("_iv_rerun",False):
        fyers=get_fyers()
        if fyers:
            with st.spinner("Fetching spot..."):
                dss=fetch_candles(fyers,"BSE:SENSEX-INDEX",iv_int,iv_ds)
                if dss.empty: dss=fetch_candles(fyers,"BSE:SENSEX",iv_int,iv_ds)
                dns=fetch_candles(fyers,"NSE:NIFTY50-INDEX",iv_int,iv_ds)
                if dns.empty: dns=fetch_candles(fyers,"NSE:NIFTY50",iv_int,iv_ds)
            if dss.empty or dns.empty:
                st.error("⚠️ Could not fetch spot prices.")
            else:
                for d in [dss,dns]: d.drop(index=d.index[d.index.duplicated(keep="last")],inplace=True,errors="ignore")
                last_sx=dss["close"].iloc[-1]
                cts=dss.index.intersection(dns.index)
                sm=dss["close"].reindex(cts)/dns["close"].reindex(cts)
                ivm=round(float(sm.dropna().iloc[-1]),4)
                st.session_state["iv_mult"]=ivm
                sxp=dss["close"].reindex(cts)
                def atm(s): return int(round(float(s)/500)*500)
                lo_sx=sxp.apply(atm); hi_sx=lo_sx.apply(lambda k:k+500)
                lo_nf=(lo_sx/sm.reindex(lo_sx.index).ffill()).apply(lambda k:rnd(k,50))
                hi_nf=(hi_sx/sm.reindex(hi_sx.index).ffill()).apply(lambda k:rnd(k,50))
                all_syms={}
                for k in sorted(lo_sx.unique()):
                    all_syms[f"sx_lo_CE_{k}"]=build_symbol("BSE","SENSEX",sx_exp,"C",int(k))
                    all_syms[f"sx_lo_PE_{k}"]=build_symbol("BSE","SENSEX",sx_exp,"P",int(k))
                for k in sorted(hi_sx.unique()):
                    all_syms[f"sx_hi_CE_{k}"]=build_symbol("BSE","SENSEX",sx_exp,"C",int(k))
                    all_syms[f"sx_hi_PE_{k}"]=build_symbol("BSE","SENSEX",sx_exp,"P",int(k))
                for k in sorted(lo_nf.unique()):
                    all_syms[f"nf_lo_CE_{k}"]=build_symbol("NSE","NIFTY",nf_exp,"C",int(k))
                    all_syms[f"nf_lo_PE_{k}"]=build_symbol("NSE","NIFTY",nf_exp,"P",int(k))
                for k in sorted(hi_nf.unique()):
                    all_syms[f"nf_hi_CE_{k}"]=build_symbol("NSE","NIFTY",nf_exp,"C",int(k))
                    all_syms[f"nf_hi_PE_{k}"]=build_symbol("NSE","NIFTY",nf_exp,"P",int(k))
                with st.spinner(f"Fetching {len(all_syms)} option series..."):
                    fetched={}
                    for key,sym in all_syms.items():
                        df_o=fetch_candles(fyers,sym,iv_int,iv_ds)
                        fetched[key]=df_o[~df_o.index.duplicated(keep="last")] if not df_o.empty else df_o
                r=iv_rfr/100; exp_sx=exp2date(sx_exp); exp_nf=exp2date(nf_exp)
                def div_series(spot_df,sk_series,fetched_d,pfx,exp_dt,ot):
                    oiv={}; osk={}
                    for ts in spot_df.index.intersection(sk_series.index):
                        S=spot_df.loc[ts,"close"]; K=int(sk_series.loc[ts])
                        df_o=fetched_d.get(f"{pfx}_{K}")
                        if df_o is None or df_o.empty or ts not in df_o.index: continue
                        T=max((exp_dt-ts.date()).days/365,1/365)
                        oiv[ts]=calc_iv(df_o.loc[ts,"close"],S,K,T,r,ot); osk[ts]=K
                    return pd.Series(oiv,dtype=float),pd.Series(osk,dtype=float)
                iv_sx_lo_CE,sk_sx_lo_CE=div_series(dss,lo_sx,fetched,"sx_lo_CE",exp_sx,"CE")
                iv_sx_lo_PE,sk_sx_lo_PE=div_series(dss,lo_sx,fetched,"sx_lo_PE",exp_sx,"PE")
                iv_nf_lo_CE,sk_nf_lo_CE=div_series(dns,lo_nf,fetched,"nf_lo_CE",exp_nf,"CE")
                iv_nf_lo_PE,sk_nf_lo_PE=div_series(dns,lo_nf,fetched,"nf_lo_PE",exp_nf,"PE")
                iv_sx_hi_CE,sk_sx_hi_CE=div_series(dss,hi_sx,fetched,"sx_hi_CE",exp_sx,"CE")
                iv_sx_hi_PE,sk_sx_hi_PE=div_series(dss,hi_sx,fetched,"sx_hi_PE",exp_sx,"PE")
                iv_nf_hi_CE,sk_nf_hi_CE=div_series(dns,hi_nf,fetched,"nf_hi_CE",exp_nf,"CE")
                iv_nf_hi_PE,sk_nf_hi_PE=div_series(dns,hi_nf,fetched,"nf_hi_PE",exp_nf,"PE")
                def sk_chg(sk,n=3):
                    if sk.empty: return []
                    items=list(sk.items()); chg=[]
                    rk,rs,rl=items[0][1],items[0][0],1; ck=rk
                    for ts,k in items[1:]:
                        if k==rk:
                            rl+=1
                            if rl==n and rk!=ck: chg.append((rs,int(rk))); ck=rk
                        else: rk,rs,rl=k,ts,1
                    return chg
                st.session_state.update({
                    "iv_res":{"sx_lo_CE":iv_sx_lo_CE,"sx_lo_PE":iv_sx_lo_PE,
                               "nf_lo_CE":iv_nf_lo_CE,"nf_lo_PE":iv_nf_lo_PE,
                               "sx_hi_CE":iv_sx_hi_CE,"sx_hi_PE":iv_sx_hi_PE,
                               "nf_hi_CE":iv_nf_hi_CE,"nf_hi_PE":iv_nf_hi_PE},
                    "iv_sk": {"sx_lo_CE":sk_sx_lo_CE,"sx_lo_PE":sk_sx_lo_PE,
                               "nf_lo_CE":sk_nf_lo_CE,"nf_lo_PE":sk_nf_lo_PE,
                               "sx_hi_CE":sk_sx_hi_CE,"sx_hi_PE":sk_sx_hi_PE,
                               "nf_hi_CE":sk_nf_hi_CE,"nf_hi_PE":sk_nf_hi_PE},
                    "iv_chg":{"lo_sx":sk_chg(sk_sx_lo_CE),"lo_nf":sk_chg(sk_nf_lo_CE),
                               "hi_sx":sk_chg(sk_sx_hi_CE),"hi_nf":sk_chg(sk_nf_hi_CE)},
                    "iv_lo_sx":int(lo_sx.iloc[-1]),"iv_hi_sx":int(hi_sx.iloc[-1]),
                    "iv_lo_nf":int(lo_nf.iloc[-1]),"iv_hi_nf":int(hi_nf.iloc[-1]),
                    "iv_last_sx":last_sx,
                    "iv_lo_sx_r":sorted(lo_sx.unique()),"iv_hi_sx_r":sorted(hi_sx.unique()),
                    "iv_lo_nf_r":sorted(lo_nf.unique()),"iv_hi_nf_r":sorted(hi_nf.unique()),
                })

    if "iv_res" in st.session_state:
        ivr2=st.session_state["iv_res"]; ivsk=st.session_state.get("iv_sk",{})
        ivch=st.session_state.get("iv_chg",{})
        lo_sx=st.session_state["iv_lo_sx"]; hi_sx=st.session_state["iv_hi_sx"]
        lo_nf=st.session_state["iv_lo_nf"]; hi_nf=st.session_state["iv_hi_nf"]
        lsx=st.session_state.get("iv_last_sx",0)
        def rl(a): return str(a[0]) if len(a)==1 else f"{min(a)}–{max(a)}"
        lo_sx_r=st.session_state.get("iv_lo_sx_r",[lo_sx]); hi_sx_r=st.session_state.get("iv_hi_sx_r",[hi_sx])
        lo_nf_r=st.session_state.get("iv_lo_nf_r",[lo_nf]); hi_nf_r=st.session_state.get("iv_hi_nf_r",[hi_nf])
        st.markdown(f"<div style='font-size:12px;color:#64748b;background:#f1f5f9;border-radius:6px;padding:8px 12px;margin:4px 0 10px 0;font-family:monospace;'>Sensex spot: <b>{lsx:.0f}</b> → G1: SX <b>{lo_sx}</b>/NF <b>{lo_nf}</b> | G2: SX <b>{hi_sx}</b>/NF <b>{hi_nf}</b></div>",unsafe_allow_html=True)
        CL={"sx_CE":"#f87171","sx_PE":"#fca5a5","nf_CE":"#60a5fa","nf_PE":"#93c5fd"}
        def ivcard(lbl,s,col,lot):
            if s is not None and not s.dropna().empty:
                v=s.dropna().iloc[-1]
                return f"<div style='background:#fff;border:1px solid #e2e8f0;border-top:3px solid {col};border-radius:8px;padding:10px 12px;'><div style='font-size:9px;font-weight:700;letter-spacing:1px;color:#94a3b8;text-transform:uppercase;'>{lbl}</div><div style='font-size:22px;font-weight:800;color:{col};margin:4px 0 2px 0;'>{v:.1f}%</div><div style='font-size:11px;color:#64748b;'>Lot:{lot}</div></div>"
            return f"<div style='background:#fff;border:1px solid #e2e8f0;border-top:3px solid {col};border-radius:8px;padding:10px 12px;'><div style='font-size:9px;color:#94a3b8;'>{lbl}</div><div style='font-size:16px;color:#cbd5e1;'>No data</div></div>"
        def ivchart(pfx,title,csx=None,cnf=None):
            fig=go.Figure(); nfx=pfx.replace("sx","nf")
            for key,nm,col,w in [(f"{pfx}_CE","Sensex CE",CL["sx_CE"],2),(f"{pfx}_PE","Sensex PE",CL["sx_PE"],1.5),
                                  (f"{nfx}_CE","Nifty CE", CL["nf_CE"],2),(f"{nfx}_PE","Nifty PE", CL["nf_PE"],1.5)]:
                s=ivr2.get(key,pd.Series(dtype=float)).dropna()
                sk=ivsk.get(key,pd.Series(dtype=float))
                if not s.empty:
                    ska=sk.reindex(s.index).ffill().fillna(0).astype(int)
                    lv=s.iloc[-1]; lk=int(ska.iloc[-1]) if not ska.empty else 0
                    fig.add_trace(go.Scatter(x=s.index,y=s.values,name=f"{nm}(K:{lk}·{lv:.1f}%)",
                        line=dict(color=col,width=w),
                        text=[f"K:{k}<br>IV:{iv:.2f}%" for iv,k in zip(s.values,ska.values)],
                        hovertemplate="%{text}<extra>"+nm+"</extra>"))
            for ts,nk in (csx or []):
                fig.add_shape(type="line",x0=str(ts),x1=str(ts),y0=0,y1=1,xref="x",yref="paper",line=dict(color="#f97316",width=1.5,dash="dash"))
                fig.add_annotation(x=str(ts),y=1,xref="x",yref="paper",text=f"SX→{nk}",showarrow=False,yanchor="bottom",font=dict(color="#f97316",size=9),bgcolor="rgba(255,255,255,.7)")
            for ts,nk in (cnf or []):
                fig.add_shape(type="line",x0=str(ts),x1=str(ts),y0=0,y1=1,xref="x",yref="paper",line=dict(color="#a855f7",width=1.5,dash="dot"))
                fig.add_annotation(x=str(ts),y=0,xref="x",yref="paper",text=f"NF→{nk}",showarrow=False,yanchor="top",font=dict(color="#a855f7",size=9),bgcolor="rgba(255,255,255,.7)")
            fig.update_layout(title=dict(text=title,font=dict(size=12,color="#64748b"),x=0),
                height=400,plot_bgcolor="#f8fafc",paper_bgcolor="#f8fafc",font=dict(color="#334155"),
                hovermode="x unified",margin=dict(l=10,r=10,t=40,b=10),
                legend=dict(bgcolor="#fff",bordercolor="#e2e8f0",borderwidth=1,orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                xaxis=dict(gridcolor="#e2e8f0",tickfont=dict(size=10),showspikes=True,spikemode="across",spikecolor="#94a3b8",spikethickness=1),
                yaxis=dict(gridcolor="#e2e8f0",title="IV %",tickfont=dict(size=10),showspikes=True,spikemode="across",spikecolor="#94a3b8",spikethickness=1),
                hoverlabel=dict(bgcolor="#fff",bordercolor="#e2e8f0"))
            return fig
        st.markdown(f"<div style='font-size:12px;font-weight:700;color:#64748b;margin:10px 0 6px 0;'>📉 Graph 1 — Sensex ATM <span style='color:#f87171'>{rl(lo_sx_r)}</span> / Nifty <span style='color:#60a5fa'>{rl(lo_nf_r)}</span></div>",unsafe_allow_html=True)
        c1,c2,c3,c4=st.columns(4)
        c1.markdown(ivcard("Sensex ATM CE IV",ivr2.get("sx_lo_CE"),CL["sx_CE"],SX_LOT),unsafe_allow_html=True)
        c2.markdown(ivcard("Sensex ATM PE IV",ivr2.get("sx_lo_PE"),CL["sx_PE"],SX_LOT),unsafe_allow_html=True)
        c3.markdown(ivcard("Nifty ATM CE IV", ivr2.get("nf_lo_CE"),CL["nf_CE"],NF_LOT), unsafe_allow_html=True)
        c4.markdown(ivcard("Nifty ATM PE IV", ivr2.get("nf_lo_PE"),CL["nf_PE"],NF_LOT), unsafe_allow_html=True)
        st.plotly_chart(ivchart("sx_lo",f"IV% — Sensex {rl(lo_sx_r)} & Nifty {rl(lo_nf_r)}",
            ivch.get("lo_sx"),ivch.get("lo_nf")),use_container_width=True)
        def diffchart(csk,cnk,psk,pnk,title):
            fig=go.Figure()
            for ask,bnk,nm,col in [(csk,cnk,"CE Diff","#f87171"),(psk,pnk,"PE Diff","#60a5fa")]:
                a=ivr2.get(ask,pd.Series(dtype=float)).dropna()
                b=ivr2.get(bnk,pd.Series(dtype=float)).dropna()
                idx=a.index.intersection(b.index)
                if len(idx)>0:
                    d=a.reindex(idx)-b.reindex(idx)
                    fig.add_trace(go.Scatter(x=d.index,y=d.values,name=f"{nm}(last:{d.iloc[-1]:.1f}%)",
                        line=dict(color=col,width=2),hovertemplate=f"{nm}: %{{y:.2f}}%<extra></extra>"))
            fig.add_hline(y=0,line_dash="dash",line_color="#94a3b8",line_width=1)
            fig.update_layout(title=dict(text=title,font=dict(size=12,color="#64748b"),x=0),
                height=320,plot_bgcolor="#f8fafc",paper_bgcolor="#f8fafc",font=dict(color="#334155"),
                hovermode="x unified",margin=dict(l=10,r=10,t=40,b=10),
                legend=dict(bgcolor="#fff",bordercolor="#e2e8f0",borderwidth=1,orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                xaxis=dict(gridcolor="#e2e8f0",tickfont=dict(size=10),showspikes=True,spikemode="across",spikecolor="#94a3b8",spikethickness=1),
                yaxis=dict(gridcolor="#e2e8f0",title="IV Diff %",tickfont=dict(size=10),showspikes=True,spikemode="across",spikecolor="#94a3b8",spikethickness=1),
                hoverlabel=dict(bgcolor="#fff",bordercolor="#e2e8f0"))
            return fig
        st.markdown("<div style='font-size:12px;font-weight:700;color:#64748b;margin:16px 0 6px 0;'>📊 IV Differential — Sensex IV − Nifty IV</div>",unsafe_allow_html=True)
        st.plotly_chart(diffchart("sx_lo_CE","nf_lo_CE","sx_lo_PE","nf_lo_PE",
            "Sensex CE IV − Nifty CE IV  &  Sensex PE IV − Nifty PE IV"),use_container_width=True)
        if iv_auto and iv_ds==date.today().strftime("%Y-%m-%d"):
            time.sleep(iv_sec); st.session_state["_iv_rerun"]=True; st.rerun()
    else:
        st.info("👆 Set expiry dates above and click **Fetch IV Data**.")

# ─── AUTO REFRESH ─────────────────────────────
if auto_ref and date_str==date.today().strftime("%Y-%m-%d") and not df.empty:
    time.sleep(ref_sec)
    st.session_state.df=fetch_live()
    st.rerun()
