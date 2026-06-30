"""
fyers_client.py — Option Matrix
==================================
Fyers API v3 — Auto TOTP token generation (using Fyers' own official
TOKENG.py logic — proven to work) + all live data functions.

SECRETS needed in Streamlit Cloud → Settings → Secrets:
  FYERS_CLIENT_ID  = "FAJ31919"        # Your Fyers Client ID (login id)
  FYERS_APP_ID     = "G9SMNCTH4S"      # App ID from myapi.fyers.in dashboard
  FYERS_APP_TYPE   = "100"             # Usually "100"
  FYERS_SECRET_KEY = "your_app_secret" # App Secret from myapi.fyers.in
  FYERS_PIN        = "1234"            # Your 4-digit Fyers login PIN
  FYERS_TOTP_KEY   = "BASE32SECRET..." # TOTP secret (NOT the 6-digit code)

How to get these (myapi.fyers.in/dashboard):
  FYERS_APP_ID + FYERS_APP_TYPE come from your App ID, format: "G9SMNCTH4S-100"
    → FYERS_APP_ID = "G9SMNCTH4S", FYERS_APP_TYPE = "100"
  FYERS_SECRET_KEY = "App Secret" shown on the same dashboard page
  FYERS_TOTP_KEY: myaccount.fyers.in → Manage Account → External 2FA TOTP →
    Enable → copy the secret shown (NOT the 6-digit rotating code)

Redirect URL in your Fyers app (myapi.fyers.in → Apps → Edit) must be:
  http://127.0.0.1:8080/
"""

import os, re, math, json, hashlib, time
import streamlit as st
import requests
import pyotp
import pandas as pd
from datetime import datetime, date
from collections import defaultdict
from urllib.parse import urlparse, parse_qs
from fyers_apiv3 import fyersModel

# ── Constants ─────────────────────────────────────────────────────────────────
TOKEN_FILE     = "fyers_token.json"
REDIRECT_URI   = "http://127.0.0.1:8080/"
RISK_FREE_RATE = 0.065

LOT_SIZES = {"NIFTY": 75, "SENSEX": 20, "BANKNIFTY": 35, "FINNIFTY": 40}

INDEX_SYMBOLS = {
    "NIFTY":     "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "SENSEX":    "BSE:SENSEX-INDEX",
    "FINNIFTY":  "NSE:FINNIFTY-INDEX",
}

LEG_COLORS = {1:"#2962ff",2:"#26a69a",3:"#ff9800",4:"#ef5350",5:"#9c27b0",6:"#00bcd4"}

_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_MNUM   = {m: i+1 for i, m in enumerate(_MONTHS)}

# ── Time helpers ──────────────────────────────────────────────────────────────
def ist_now():
    return pd.Timestamp.now(tz="Asia/Kolkata").replace(tzinfo=None)

def is_market_open():
    now = ist_now()
    if now.weekday() >= 5: return False
    from datetime import time as _t
    return _t(9, 15) <= now.time() <= _t(15, 30)

def market_status():
    return is_market_open(), ist_now()

def market_badge_html():
    open_, now = market_status()
    ts = now.strftime("%H:%M:%S")
    if open_:
        return (f'<span style="color:#26a69a;font-weight:600;">🟢 OPEN</span> '
                f'<span style="color:#787b86;font-size:11px;">{ts} IST</span>')
    return (f'<span style="color:#ef5350;font-weight:600;">🔴 CLOSED</span> '
            f'<span style="color:#787b86;font-size:11px;">{ts} IST</span>')

# ── Secrets helper ────────────────────────────────────────────────────────────
def _sec(k, default=""):
    try:
        val = st.secrets.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(k, default).strip()


def debug_secrets():
    """Returns a dict showing which Fyers secret keys are visible right now,
    without exposing their values. Call this from anywhere in the app
    (e.g. temporarily in a tab) to diagnose 'Missing secrets' errors."""
    keys = ["FYERS_CLIENT_ID", "FYERS_APP_ID", "FYERS_APP_TYPE",
            "FYERS_SECRET_KEY", "FYERS_PIN", "FYERS_TOTP_KEY"]
    out = {}
    try:
        top_level_keys = list(st.secrets.keys())
    except Exception as e:
        top_level_keys = [f"<error reading st.secrets: {e}>"]
    for k in keys:
        v = _sec(k)
        out[k] = f"present (len={len(v)})" if v else "MISSING"
    out["_all_top_level_secret_keys"] = top_level_keys
    return out

# ── Token file ────────────────────────────────────────────────────────────────
def _save_token(token):
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump({"token": token, "date": date.today().isoformat()}, f)
    except Exception: pass

def _load_token():
    try:
        d = json.load(open(TOKEN_FILE))
        if d.get("date") == date.today().isoformat() and len(d.get("token","")) > 20:
            return d["token"]
    except Exception: pass
    return None

# ── TOTP LOGIN — exact logic from Fyers' official TOKENG.py ──────────────────
_BASE_V2 = "https://api-t2.fyers.in/vagator/v2"
_BASE_V3 = "https://api-t1.fyers.in/api/v3"

def _step1_send_otp(client_id):
    """Step 1: send login OTP. client_id is the PLAIN Fyers login id (not base64)."""
    r = requests.post(f"{_BASE_V2}/send_login_otp",
                      json={"fy_id": client_id, "app_id": "2"}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Step 1 (send OTP) failed: HTTP {r.status_code}: {r.text}")
    d = r.json()
    if "request_key" not in d:
        raise RuntimeError(f"Step 1 (send OTP) failed: {d}")
    return d["request_key"]

def _step2_verify_totp(request_key, totp_secret):
    """Step 2: verify TOTP code."""
    totp_code = pyotp.TOTP(totp_secret).now()
    r = requests.post(f"{_BASE_V2}/verify_otp",
                      json={"request_key": request_key, "otp": totp_code}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(
            f"Step 2 (verify TOTP) failed: HTTP {r.status_code}: {r.text}\n"
            "→ FYERS_TOTP_KEY must be the Base32 secret (not the 6-digit code).")
    d = r.json()
    if "request_key" not in d:
        raise RuntimeError(f"Step 2 (verify TOTP) failed: {d}")
    return d["request_key"]

def _step3_verify_pin(request_key, pin):
    """Step 3: verify PIN. pin is PLAIN text (not base64)."""
    r = requests.post(f"{_BASE_V2}/verify_pin",
                      json={"request_key": request_key,
                            "identity_type": "pin", "identifier": pin}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(
            f"Step 3 (verify PIN) failed: HTTP {r.status_code}: {r.text}\n"
            "→ Check FYERS_PIN — your 4-digit Fyers login PIN.")
    d = r.json()
    if "data" not in d or "access_token" not in d.get("data", {}):
        raise RuntimeError(f"Step 3 (verify PIN) failed: {d}")
    return d["data"]["access_token"]

def _step4_get_authcode(client_id, app_id, app_type, bearer_token):
    """
    Step 4: exchange bearer token for auth_code.
    SUCCESS is HTTP 308 (redirect status) — response body still has JSON
    with an "Url" field containing the auth_code as a query param.
    """
    r = requests.post(f"{_BASE_V3}/token",
        json={"fyers_id": client_id, "app_id": app_id,
              "redirect_uri": REDIRECT_URI, "appType": app_type,
              "code_challenge": "", "state": "sample_state",
              "scope": "", "nonce": "", "response_type": "code",
              "create_cookie": True},
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=15)
    if r.status_code != 308:
        raise RuntimeError(
            f"Step 4 (get auth_code) failed: HTTP {r.status_code}: {r.text}\n"
            f"→ 'redirectUrl mismatch': set Redirect URL in myapi.fyers.in to "
            f"exactly: {REDIRECT_URI}\n"
            f"→ 'apptype mismatch': check FYERS_APP_ID / FYERS_APP_TYPE")
    d   = r.json()
    url = d.get("Url", "")
    qs  = parse_qs(urlparse(url).query)
    auth_code = qs.get("auth_code", [None])[0]
    if not auth_code:
        raise RuntimeError(f"Step 4: no auth_code in Url field: {d}")
    return auth_code

def _sha256_apphash(app_id, app_type, app_secret):
    """
    EXACT hash format from Fyers' official script:
    SHA256(f"{appId}-{appType}:{appSecret}")
    e.g. SHA256("G9SMNCTH4S-100:RD4M0JLROL")
    """
    message = f"{app_id}-{app_type}:{app_secret}".encode()
    return hashlib.sha256(message).hexdigest()

def _step5_validate_authcode(auth_code, app_id, app_type, app_secret):
    """Step 5: exchange auth_code for final access_token."""
    app_hash = _sha256_apphash(app_id, app_type, app_secret)
    r = requests.post(f"{_BASE_V3}/validate-authcode",
        json={"grant_type": "authorization_code",
              "appIdHash": app_hash, "code": auth_code}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(
            f"Step 5 (validate authcode) failed: HTTP {r.status_code}: {r.text}")
    d = r.json()
    if "access_token" not in d:
        raise RuntimeError(f"Step 5 (validate authcode) failed: {d}")
    return d["access_token"]

def _generate_token():
    """
    Full 5-step TOTP login using Fyers' own proven logic.
    Returns the FULL token in the format fyersModel expects:
      "APP_ID-APP_TYPE:access_token"
    """
    client_id = _sec("FYERS_CLIENT_ID")
    app_id    = _sec("FYERS_APP_ID")
    app_type  = _sec("FYERS_APP_TYPE", "100")
    app_sec   = _sec("FYERS_SECRET_KEY")
    pin       = _sec("FYERS_PIN")
    totp_key  = _sec("FYERS_TOTP_KEY")

    rk1     = _step1_send_otp(client_id)
    rk2     = _step2_verify_totp(rk1, totp_key)
    bearer  = _step3_verify_pin(rk2, pin)
    auth    = _step4_get_authcode(client_id, app_id, app_type, bearer)
    raw_tok = _step5_validate_authcode(auth, app_id, app_type, app_sec)

    # Full token format required by fyersModel: "APPID-APPTYPE:access_token"
    return f"{app_id}-{app_type}:{raw_tok}"

# ── Public auth API ───────────────────────────────────────────────────────────
def get_token():
    """
    Returns a valid full Fyers token (format: "APPID-APPTYPE:access_token").
    1. st.session_state (fastest)
    2. fyers_token.json (survives hot-reload, one per day)
    3. Generate fresh via TOTP
    """
    t = st.session_state.get("_fyers_tok")
    if t and len(t) > 20: return t

    t = _load_token()
    if t:
        st.session_state["_fyers_tok"] = t
        return t

    required = ["FYERS_CLIENT_ID","FYERS_APP_ID","FYERS_APP_TYPE",
                "FYERS_SECRET_KEY","FYERS_PIN","FYERS_TOTP_KEY"]
    miss = [k for k in required if not _sec(k)]
    if miss:
        raise RuntimeError(
            f"Missing Fyers secrets: {', '.join(miss)}\n\n"
            "Add in Streamlit Cloud → Settings → Secrets:\n"
            '  FYERS_CLIENT_ID  = "FAJ31919"\n'
            '  FYERS_APP_ID     = "G9SMNCTH4S"\n'
            '  FYERS_APP_TYPE   = "100"\n'
            '  FYERS_SECRET_KEY = "your_app_secret"\n'
            '  FYERS_PIN        = "1234"\n'
            '  FYERS_TOTP_KEY   = "BASE32SECRET..."')

    token = _generate_token()
    _save_token(token)
    st.session_state["_fyers_tok"] = token
    return token

def get_fyers_client():
    """Returns authenticated FyersModel, cached in session state."""
    if st.session_state.get("_fc"): return st.session_state["_fc"]
    app_id_full = _sec("FYERS_APP_ID") + "-" + _sec("FYERS_APP_TYPE", "100")
    fc = fyersModel.FyersModel(
        client_id=app_id_full, token=get_token(), is_async=False, log_path="")
    st.session_state["_fc"] = fc
    return fc

def refresh_token():
    """Force fresh token on next call."""
    st.session_state.pop("_fc", None)
    st.session_state.pop("_fyers_tok", None)
    try: os.remove(TOKEN_FILE)
    except FileNotFoundError: pass
    for k in list(st.session_state.keys()):
        if k.startswith("exp_") or k.startswith("stk_"): del st.session_state[k]

def render_token_status():
    st.markdown(market_badge_html(), unsafe_allow_html=True)
    col1, col2 = st.columns([3,1])
    with col1:
        tok = st.session_state.get("_fyers_tok") or _load_token()
        if tok:
            st.markdown('<span style="font-size:11px;color:#26a69a;">🔑 Token active</span>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<span style="font-size:11px;color:#ff9800;">⏳ Not loaded</span>',
                        unsafe_allow_html=True)
    with col2:
        if st.button("🔄", key="_refresh_tok", help="Refresh Fyers token"):
            refresh_token(); st.rerun()

# ── Small parsing helpers (used by live_bhavcopy.py) ──────────────────────────
def _to_float(v):
    """Safe float conversion — returns 0.0 for None/empty/unparseable values."""
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_expiry_date(edata_entry):
    """Parse one entry from Fyers optionchain's expiryData list into a date object.
    Each entry looks like {"date": "DD-MM-YYYY", "expiry": "<epoch>"}."""
    d = edata_entry.get("date", "") if isinstance(edata_entry, dict) else ""
    dd, mm, yyyy = d.split("-")
    return date(int(yyyy), int(mm), int(dd))


def get_chain(index, epoch):
    """Fetch the full option chain for `index` at a specific expiry `epoch`
    (the raw 'expiry' timestamp string Fyers returns in expiryData)."""
    fc_client = get_fyers_client()
    sym = INDEX_SYMBOLS.get(index, f"NSE:{index}-INDEX")
    r = fc_client.optionchain(data={"symbol": sym, "strikecount": 0,
                                      "timestamp": str(epoch)})
    if not (r and r.get("s") == "ok"):
        raise ValueError(f"Cannot load chain for {index} @ {epoch}: {r}")
    return r.get("data", {}).get("optionsChain", [])


# ── Expiries ──────────────────────────────────────────────────────────────────
def get_expiries(index):
    ck = f"exp_{index}"
    if st.session_state.get(ck): return list(st.session_state[ck].keys())
    fc  = get_fyers_client()
    sym = INDEX_SYMBOLS.get(index, f"NSE:{index}-INDEX")
    r   = fc.optionchain(data={"symbol": sym, "strikecount": 1, "timestamp": ""})
    if not (r and r.get("s") == "ok"):
        raise ValueError(f"Cannot load expiries for {index}: {r}")
    raw = r.get("data", {}).get("expiryData", [])
    parsed = []
    for e in raw:
        if not isinstance(e, dict): continue
        try:
            dd, mm, yy4 = e["date"].split("-")
            dd, mm, yy4 = int(dd), int(mm), int(yy4)
            parsed.append((yy4%100, mm, dd, _MONTHS[mm-1]))
        except Exception: continue
    if not parsed: raise ValueError(f"No expiry dates for {index}")
    by_month = defaultdict(list)
    for yy,mm,dd,mon in parsed: by_month[(yy,mm)].append(dd)
    last = {k: max(v) for k,v in by_month.items()}
    result = {}
    for yy,mm,dd,mon in parsed:
        is_m  = (dd == last[(yy,mm)])
        code  = f"{yy:02d}{mon}" if is_m else f"{yy:02d}{mm:02d}{dd:02d}"
        label = f"{dd:02d} {mon} {yy:02d} ({'M' if is_m else 'W'})"
        result[label] = code
    st.session_state[ck] = result
    return list(result.keys())

# Alias — spread_chart.py / position_analysis.py call fc.expiry_labels(),
# but the actual implementation above is named get_expiries(). Without this
# alias every call raises AttributeError, which is caught and silently
# stored in st.session_state["_fy_err"] (or simply swallowed depending on
# the call site), producing the empty-expiry-list "Waiting for Fyers
# expiry data…" message with no visible error.
expiry_labels = get_expiries

def find_expiry(index, label):
    """Return {'code':..., 'date':...} for a given expiry label, or None."""
    code = _label_to_code(label, index)
    if not code:
        return None
    try:
        return {"code": code, "date": _expiry_date(label, index)}
    except Exception:
        return None

def _label_to_code(label, index="NIFTY"):
    """Convert expiry label → Fyers code. Works WITHOUT session state."""
    cached = st.session_state.get(f"exp_{index}", {}).get(label)
    if cached: return cached
    try:
        clean = re.sub(r'\s*\([WM]\)\s*$', '', label.strip(), flags=re.IGNORECASE).strip()
        parts = clean.split()
        dd, mon, yy = int(parts[0]), parts[1][:3].upper(), int(parts[2])
        mm = _MNUM.get(mon, 0)
        if mm > 0:
            is_m = bool(re.search(r'\(M\)', label, re.IGNORECASE))
            return f"{yy:02d}{mon}" if is_m else f"{yy:02d}{mm:02d}{dd:02d}"
    except Exception: pass
    return label.strip()

def _expiry_date(label, index="NIFTY"):
    import calendar
    code = _label_to_code(label, index).upper()
    if any(c.isalpha() for c in code):
        yy=int(code[:2]); mon=code[2:5]; mm=_MNUM[mon]
        return date(2000+yy, mm, calendar.monthrange(2000+yy,mm)[1])
    return date(2000+int(code[:2]), int(code[2:4]), int(code[4:6]))

def years_to_expiry(label, index="NIFTY"):
    try: return max((_expiry_date(label,index)-date.today()).days, 1)/365.
    except Exception: return 30/365.

# ── Strikes ───────────────────────────────────────────────────────────────────
def get_strikes(index, expiry_label):
    code = _label_to_code(expiry_label, index)
    ck   = f"stk_{index}_{code}"
    if st.session_state.get(ck): return st.session_state[ck]
    fc  = get_fyers_client()
    sym = INDEX_SYMBOLS.get(index, f"NSE:{index}-INDEX")
    r   = fc.optionchain(data={"symbol": sym, "strikecount": 0, "timestamp": ""})
    if r and r.get("s") == "ok":
        chain   = r.get("data", {}).get("optionsChain", [])
        strikes = sorted({int(float(o["strikePrice"]))
                          for o in chain if isinstance(o,dict) and o.get("strikePrice")})
        if strikes:
            st.session_state[ck] = strikes
            return strikes
    atm  = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(index, 22800)
    step = 50 if index=="NIFTY" else (100 if index=="BANKNIFTY" else 500)
    return list(range(atm-40*step, atm+41*step, step))

# ── Symbol builder ────────────────────────────────────────────────────────────
def build_symbol(index, expiry_label, opt_type, strike):
    exch = "BSE" if index in ("SENSEX","BANKEX") else "NSE"
    code = _label_to_code(expiry_label, index).strip().upper()
    ot   = "CE" if opt_type.upper() in ("CE","C","CALL") else "PE"
    stk  = str(int(float(str(strike).replace(",",""))))
    if any(c.isalpha() for c in code):
        return f"{exch}:{index}{code}{ot}{stk}"
    if len(code) == 6 and code.isdigit():
        yy = code[:2]; mm = str(int(code[2:4])); dd = code[4:6]
        return f"{exch}:{index}{yy}{mm}{dd}{ot}{stk}"
    return f"{exch}:{index}{code}{ot}{stk}"

def leg_to_symbol(leg):
    return build_symbol(leg["index"], leg["expiry"], leg.get("opt_type", leg.get("cp")), leg["strike"])

def get_lot_size(index, symbol=None):
    return LOT_SIZES.get(index, 75)

# ── Live quotes ───────────────────────────────────────────────────────────────
def get_quotes(symbols):
    """Batch quotes in ONE call. Uses prev_close when lp=0 (market closed)."""
    if not symbols: return {}
    try:
        fc   = get_fyers_client()
        syms = ",".join(symbols) if isinstance(symbols, list) else symbols
        r    = fc.quotes(data={"symbols": syms})
        if r.get("s") != "ok": return {}
        out = {}
        for d in r.get("d", []):
            v   = d.get("v", {})
            sym = v.get("symbol") or d.get("n","")
            ltp = float(v.get("lp", 0))
            pre = float(v.get("prev_close_price", 0))
            eff = ltp if ltp > 0 else pre
            out[sym] = {
                "ltp": eff, "ltp_live": ltp, "prev_close": pre,
                "bid": float(v.get("bid", eff*.998)),
                "ask": float(v.get("ask", eff*1.002)),
                "high": float(v.get("high_price", eff)),
                "low":  float(v.get("low_price",  eff)),
                "open": float(v.get("open_price", eff)),
                "oi":   int(v.get("open_interest", v.get("oi", 0))),
                "volume": int(v.get("volume", 0)),
                "ch": float(v.get("ch", 0)), "chp": float(v.get("chp", 0)),
                "market_open": ltp > 0,
            }
        return out
    except Exception: return {}

def get_quote(symbol):
    return get_quotes([symbol]).get(symbol, {})

def get_ltp(index, strike, expiry, cp):
    sym = build_symbol(index, expiry, cp, strike)
    return get_quotes([sym]).get(sym, {}).get("ltp", 0.0)

def underlying_ltp(index):
    sym = INDEX_SYMBOLS.get(index)
    if not sym: return 0.0
    return get_quotes([sym]).get(sym, {}).get("ltp", 0.0)

get_spot = underlying_ltp

def get_spread_value(legs):
    """Live spread value via ONE batch quote call. Returns (value, error)."""
    sym_map = {}
    for leg in legs:
        try: sym_map[leg_to_symbol(leg)] = leg
        except Exception: pass
    if not sym_map: return 0.0, "No valid symbols"
    quotes = get_quotes(list(sym_map))
    if not quotes: return 0.0, "No quotes returned — check token"
    total = 0.0; missing = []
    for sym, leg in sym_map.items():
        ltp = quotes.get(sym, {}).get("ltp", 0.0)
        side = leg.get("bs") or leg.get("side")
        if ltp:
            sign = 1 if side == "Buy" else -1
            total += sign * ltp * leg.get("ratio", 1)
        else:
            missing.append(f"{leg['index']} {leg['strike']}{leg.get('cp',leg.get('opt_type'))}")
    err = f"No price: {', '.join(missing)}" if missing else None
    return round(total, 2), err

def spread_value(legs, quotes):
    """Compute spread value from an ALREADY-FETCHED quotes dict (no extra API call).
    Used by spread_chart.py's live feed, which fetches quotes once and reuses them.
    Returns a single float (not a tuple) — raises if a required quote is missing."""
    total = 0.0
    missing = []
    for leg in legs:
        try:
            sym = leg_to_symbol(leg)
        except Exception:
            continue
        ltp = quotes.get(sym, {}).get("ltp", 0.0)
        side = leg.get("bs") or leg.get("side")
        if ltp:
            sign = 1 if side == "Buy" else -1
            total += sign * ltp * leg.get("ratio", 1)
        else:
            missing.append(f"{leg.get('index')} {leg.get('strike')}{leg.get('cp', leg.get('opt_type'))}")
    if missing:
        raise ValueError(f"No price for: {', '.join(missing)}")
    return round(total, 2)

# ── Candles ───────────────────────────────────────────────────────────────────
TIMEFRAMES = {"1m":"1","3m":"3","5m":"5","10m":"10","15m":"15","30m":"30","60m":"60","1D":"D"}
def resolution_for(tf): return TIMEFRAMES.get(tf, "1")

def get_candles(symbol, range_from=None, range_to=None, resolution="1"):
    today = ist_now().strftime("%Y-%m-%d")
    if range_from is None: range_from = today
    if range_to   is None: range_to   = today
    try:
        fc = get_fyers_client()
        r  = fc.history(data={"symbol": symbol, "resolution": str(resolution),
                               "date_format": "1", "range_from": range_from,
                               "range_to": range_to, "cont_flag": "1"})
        if not (r.get("s") == "ok" and r.get("candles")):
            return pd.DataFrame()
        df = pd.DataFrame(r["candles"], columns=["ts","o","h","l","c","volume"])
        df["ts"] = (pd.to_datetime(df["ts"], unit="s")
                    .dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata").dt.tz_localize(None))
        return df[["ts","o","h","l","c"]].rename(columns={"c":"close"}).assign(
            open=lambda x: df["o"], high=lambda x: df["h"], low=lambda x: df["l"]
        )[["ts","open","high","low","close"]]
    except Exception: return pd.DataFrame()

# ── Black-Scholes ─────────────────────────────────────────────────────────────
def _N(x): return (1+math.erf(x/math.sqrt(2)))/2
def _n(x): return math.exp(-.5*x*x)/math.sqrt(2*math.pi)

def bs_price(S,K,T,r,sig,cp):
    if T<=0 or sig<=0: return max(0.,(S-K) if cp=="CE" else(K-S))
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    return S*_N(d1)-K*math.exp(-r*T)*_N(d2) if cp=="CE" else K*math.exp(-r*T)*_N(-d2)-S*_N(-d1)

def implied_vol(price, S, K, T, opt_type="CE", r=RISK_FREE_RATE):
    if any(x<=0 for x in [price,S,K,T]): return 0.0
    lo,hi=.001,5.
    mid=.5
    for _ in range(200):
        mid=(lo+hi)/2; p=bs_price(S,K,T,r,mid,opt_type)
        if abs(p-price)<1e-4: break
        lo,hi=(mid,hi) if p<price else(lo,mid)
    return round(mid, 4)   # returns as decimal fraction (0.18 = 18%)

def bs_greeks(S,K,T,iv,opt_type="CE",r=RISK_FREE_RATE):
    """iv passed as decimal fraction (0.18 = 18%)."""
    sig=iv
    if T<=0 or sig<=0: return{"delta":0,"gamma":0,"vega":0,"theta":0}
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    pdf=_n(d1); g=pdf/(S*sig*math.sqrt(T)); v=S*pdf*math.sqrt(T)/100
    d=_N(d1) if opt_type=="CE" else _N(d1)-1
    t=(-(S*pdf*sig)/(2*math.sqrt(T))+(-r*K*math.exp(-r*T)*_N(d2) if opt_type=="CE"
       else r*K*math.exp(-r*T)*_N(-d2)))/365
    return{"delta":round(d,4),"gamma":round(g,6),"vega":round(v,4),"theta":round(t,4)}

# ── Payoff helpers (for strategy builder / position analysis) ────────────────
def payoff_at(legs, spot):
    """legs: [{opt_type, strike, side, qty, premium}]. Returns P&L in rupees."""
    total = 0.0
    for lg in legs:
        K = lg["strike"]; prem = lg["premium"]; qty = lg["qty"]
        intrinsic = max(0, spot-K) if lg["opt_type"]=="CE" else max(0, K-spot)
        pnl = (intrinsic - prem) * qty
        total += pnl if lg["side"]=="Buy" else -pnl
    return total

def payoff_curve(legs, spots):
    return [payoff_at(legs, s) for s in spots]

def payoff_stats(spots, pnl):
    mx, mn = max(pnl), min(pnl)
    bes = []
    for i in range(1, len(pnl)):
        if (pnl[i-1] < 0) != (pnl[i] < 0):
            bes.append(spots[i-1] + (spots[i]-spots[i-1]) *
                      (0-pnl[i-1])/(pnl[i]-pnl[i-1]) if pnl[i]!=pnl[i-1] else spots[i])
    return mx, mn, bes

def leg_sign(leg):
    return 1.0 if leg.get("side","Buy")=="Buy" else -1.0
