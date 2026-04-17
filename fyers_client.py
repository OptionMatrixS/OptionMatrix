"""
fyers_client.py  —  Option Matrix  (Fyers API v3)
=================================================
Streamlit secrets required:
  FYERS_CLIENT_ID  = "ABCD1234-100"
  FYERS_SECRET_KEY = "xxxxxxxxxxxxxxxx"
  FYERS_USERNAME   = "XY12345"           # your Fyers client / FY ID
  FYERS_PIN        = "1234"
  FYERS_TOTP_KEY   = "BASE32TOTPSECRET"  # long key from TOTP setup, NOT 6-digit code

Redirect URL in Fyers API dashboard:
  https://trade.fyers.in/api-login/redirect-uri/index.html

Why this redirect URI:
  The TOTP flow does not open a browser, so we use Fyers' own hosted
  redirect page — the same one used by every publicly available working
  Fyers TOTP script.  127.0.0.1 requires a local server and will ALWAYS
  fail on Streamlit Cloud.
"""

import os, base64, hashlib, math, json
import streamlit as st
import pandas as pd
import requests as _req
import pyotp
from datetime import datetime, date, timedelta
from collections import defaultdict
from urllib.parse import parse_qs, urlparse
from fyers_apiv3 import fyersModel

# ─── Constants ────────────────────────────────────────────────────────────────
REDIRECT_URI   = "https://trade.fyers.in/api-login/redirect-uri/index.html"
TOKEN_FILE     = "fyers_token.txt"
RISK_FREE_RATE = 0.065
_MONTHS        = ["JAN","FEB","MAR","APR","MAY","JUN",
                  "JUL","AUG","SEP","OCT","NOV","DEC"]
_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}

# ─────────────────────────────────────────────────────────────────────────────
# SECRETS
# ─────────────────────────────────────────────────────────────────────────────

def _s(key: str) -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, "").strip()

def _b64(v) -> str:
    return base64.b64encode(str(v).encode()).decode()

# ─────────────────────────────────────────────────────────────────────────────
# TOTP LOGIN  —  5-step flow identical to every working Fyers TOTP script
# ─────────────────────────────────────────────────────────────────────────────

def _generate_token(client_id, secret_key, username, pin, totp_key) -> tuple:
    """
    All 5 args passed explicitly — never reads st.secrets here
    so it is safe to call from inside @st.cache_resource.
    Returns (access_token, None) or (None, error_string).
    """
    app_id = client_id.split("-")[0]        # "ABCD1234-100" → "ABCD1234"

    try:
        sess = _req.Session()

        # Step 1 ── send OTP to registered mobile/email
        r1 = sess.post(
            "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
            json={"fy_id": _b64(username), "app_id": "2"},
            timeout=15)
        if r1.status_code == 429:
            return None, "Fyers rate-limited (HTTP 429). Wait 60 s then Refresh Token."
        try:
            d1 = r1.json()
        except Exception:
            return None, f"Step 1 bad response ({r1.status_code}): {r1.text[:200]}"
        if d1.get("s") != "ok":
            return None, f"Step 1 failed: {d1}"

        # Step 2 ── verify TOTP code (generated from base32 key)
        totp_code = pyotp.TOTP(totp_key).now()
        r2 = sess.post(
            "https://api-t2.fyers.in/vagator/v2/verify_otp",
            json={"request_key": d1["request_key"], "otp": totp_code},
            timeout=15)
        try:
            d2 = r2.json()
        except Exception:
            return None, f"Step 2 bad response: {r2.text[:200]}"
        if d2.get("s") != "ok":
            return None, (
                f"Step 2 (TOTP) failed: {d2}\n"
                "FYERS_TOTP_KEY must be the long Base32 secret (e.g. JBSWY3DPEHPK3PXP) "
                "shown during TOTP setup — NOT the 6-digit changing code."
            )

        # Step 3 ── verify 4-digit PIN
        r3 = sess.post(
            "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
            json={"request_key": d2["request_key"],
                  "identity_type": "pin",
                  "identifier": _b64(pin)},
            timeout=15)
        try:
            d3 = r3.json()
        except Exception:
            return None, f"Step 3 bad response: {r3.text[:200]}"
        if d3.get("s") != "ok":
            return None, f"Step 3 (PIN) failed: {d3} — check FYERS_PIN"

        # Step 4 ── get auth-code
        # appType MUST match what is set in myapi.fyers.in for your app.
        # For personal apps created on the dashboard it is always "100".
        r4 = sess.post(
            "https://api-t1.fyers.in/api/v3/token",
            json={
                "fyers_id":       username,
                "app_id":         app_id,
                "redirect_uri":   REDIRECT_URI,
                "appType":        "100",
                "code_challenge": "",
                "state":          "sample",
                "scope":          "",
                "nonce":          "",
                "response_type":  "code",
                "create_cookie":  True,
            },
            headers={"Authorization": f"Bearer {d3['data']['access_token']}"},
            timeout=15)
        try:
            d4 = r4.json()
        except Exception:
            return None, f"Step 4 bad response: {r4.text[:200]}"
        if d4.get("s") != "ok":
            return None, (
                f"Step 4 (auth-code) failed: {d4}\n"
                f"Redirect URL in Fyers API dashboard MUST be exactly:\n"
                f"  {REDIRECT_URI}\n"
                f"Go to myapi.fyers.in → Apps → your app → Edit → Redirect URL"
            )

        # Extract auth_code from wherever Fyers puts it
        data = d4.get("data", {})
        url  = d4.get("Url", "") or data.get("url", "")
        auth_code = (
            data.get("auth_code")
            or data.get("auth")
            or parse_qs(urlparse(url).query).get("auth_code", [None])[0]
        )
        if not auth_code:
            return None, f"Step 4: no auth_code found in {d4}"

        # Step 5 ── exchange auth_code for access_token (new v3 method: SHA-256 hash)
        app_hash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
        r5 = sess.post(
            "https://api-t1.fyers.in/api/v3/validate-authcode",
            json={"grant_type": "authorization_code",
                  "appIdHash":  app_hash,
                  "code":       auth_code},
            timeout=15)
        try:
            d5 = r5.json()
        except Exception:
            return None, f"Step 5 bad response: {r5.text[:200]}"
        token = d5.get("access_token")

        if not token:
            # Fallback: legacy SessionModel (some older app versions)
            try:
                sess_model = fyersModel.SessionModel(
                    client_id=client_id, secret_key=secret_key,
                    redirect_uri=REDIRECT_URI,
                    response_type="code", grant_type="authorization_code")
                sess_model.set_token(auth_code)
                d5b   = sess_model.generate_token()
                token = d5b.get("access_token")
                if not token:
                    return None, f"Step 5 both methods failed: {d5} / {d5b}"
            except Exception as e:
                return None, f"Step 5 failed: {d5} / SDK error: {e}"

        return token, None

    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# CACHED TOKEN  (credentials as args → safe inside @st.cache_resource)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _cached_token(client_id, secret_key, username, pin, totp_key) -> tuple:
    """Runs _generate_token once per Streamlit server restart. Caches result."""
    # Try persisted file first (survives hot-reloads)
    try:
        with open(TOKEN_FILE) as f:
            tok = f.read().strip()
        if tok and len(tok) > 20:
            return tok, None
    except FileNotFoundError:
        pass

    token, err = _generate_token(client_id, secret_key, username, pin, totp_key)
    if token:
        try:
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
        except Exception:
            pass
        return token, None
    return None, err


def get_token() -> str:
    """
    Public entry-point for all modules.
    Reads st.secrets in normal Streamlit context, then delegates to cached fn.
    Raises RuntimeError with a clear message on failure.
    """
    cid  = _s("0Z0FI0BJS0-100")
    sec  = _s("MZS89VWU3I")
    user = _s("XA03074")
    pin  = _s("9518")
    totp = _s("MM3N4EAJDKRHPNEPFQXJ74LBHYLR74NK")

    missing = [k for k, v in {
        "FYERS_CLIENT_ID": cid, "FYERS_SECRET_KEY": sec,
        "FYERS_USERNAME": user, "FYERS_PIN": pin, "FYERS_TOTP_KEY": totp,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing Fyers secrets: {', '.join(missing)}\n"
            f"Add them in Streamlit Cloud → Settings → Secrets:\n"
            f'  FYERS_CLIENT_ID  = "XXXX-100"\n'
            f'  FYERS_SECRET_KEY = "..."\n'
            f'  FYERS_USERNAME   = "XY12345"\n'
            f'  FYERS_PIN        = "1234"\n'
            f'  FYERS_TOTP_KEY   = "BASE32SECRET"'
        )

    token, err = _cached_token(cid, sec, user, pin, totp)
    if token:
        return token
    raise RuntimeError(
        f"Fyers login failed:\n{err}\n\n"
        f"Redirect URL in Fyers API dashboard must be:\n  {REDIRECT_URI}"
    )


def get_fyers_client():
    """Returns authenticated FyersModel, cached in session state."""
    if st.session_state.get("_fc"):
        return st.session_state._fc
    tok    = get_token()
    cid    = _s("FYERS_CLIENT_ID")
    client = fyersModel.FyersModel(client_id=cid, token=tok, log_path="")
    st.session_state._fc = client
    return client


def refresh_token():
    """Clear everything so next call generates a fresh token."""
    _cached_token.clear()
    st.session_state.pop("_fc", None)
    try:
        os.remove(TOKEN_FILE)
    except FileNotFoundError:
        pass
    for k in list(st.session_state.keys()):
        if k.startswith("expiries_") or k.startswith("strikes_"):
            del st.session_state[k]


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRIES
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _fetch_expiry_map(token: str, cid: str, sym: str) -> dict:
    """{label: code} for all future expiries. Cached per (token, sym)."""
    try:
        fyers = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
        resp  = fyers.optionchain(
            data={"symbol": sym, "strikecount": 1, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            return {}
        raw    = resp.get("data", {}).get("expiryData", [])
        parsed = []
        for e in raw:
            if not isinstance(e, dict):
                continue
            try:
                dd, mm, yy4 = e["date"].split("-")
                dd, mm, yy4 = int(dd), int(mm), int(yy4)
            except Exception:
                continue
            parsed.append((yy4 % 100, mm, dd, _MONTHS[mm-1]))

        by_month = defaultdict(list)
        for yy, mm, dd, mon in parsed:
            by_month[(yy, mm)].append(dd)
        last_day = {k: max(v) for k, v in by_month.items()}

        result = {}
        for yy, mm, dd, mon in parsed:
            is_m = (dd == last_day[(yy, mm)])
            if is_m:
                code  = f"{yy:02d}{mon}"           # 26MAY
                label = f"{dd:02d} {mon} {yy:02d} (M)"
            else:
                code  = f"{yy:02d}{mm:02d}{dd:02d}" # 260516
                label = f"{dd:02d} {mon} {yy:02d} (W)"
            result[label] = code
        return result
    except Exception:
        return {}


def get_expiries(index: str) -> list:
    cache = f"expiries_{index}"
    if st.session_state.get(cache):
        return list(st.session_state[cache].keys())
    tok  = get_token()
    cid  = _s("FYERS_CLIENT_ID")
    sym  = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
    data = _fetch_expiry_map(tok, cid, sym)
    if not data:
        raise ValueError(
            f"No expiries returned from Fyers for {index}.\n"
            f"Token may be expired — click Refresh Token in the sidebar.")
    st.session_state[cache] = data
    return list(data.keys())


def _label_to_code(index: str, label: str) -> str:
    data = st.session_state.get(f"expiries_{index}", {})
    return data.get(label, label)


def _code_to_date(code: str) -> date:
    import calendar
    code = code.strip().upper()
    mmap = {m: i+1 for i, m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):
        yy = int(code[:2]); mon = code[2:5]; mm = mmap[mon]
        dd = calendar.monthrange(2000+yy, mm)[1]
        return date(2000+yy, mm, dd)
    return date(2000+int(code[:2]), int(code[2:4]), int(code[4:6]))


def _dte(label: str, index: str = "") -> float:
    try:
        code = _label_to_code(index, label) if index else label
        days = (_code_to_date(code) - datetime.now().date()).days
        return max(days, 1) / 365.0
    except Exception:
        return 30 / 365.0


# ─────────────────────────────────────────────────────────────────────────────
# STRIKES
# ─────────────────────────────────────────────────────────────────────────────

def get_strikes(index: str, expiry_label: str) -> list:
    code  = _label_to_code(index, expiry_label)
    cache = f"strikes_{index}_{code}"
    if st.session_state.get(cache):
        return st.session_state[cache]
    try:
        fyers = get_fyers_client()
        sym   = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
        resp  = fyers.optionchain(
            data={"symbol": sym, "strikecount": 50, "timestamp": ""})
        if resp and resp.get("s") == "ok":
            strikes = set()
            for opt in resp.get("data", {}).get("optionsChain", []):
                try:
                    strikes.add(int(float(opt["strikePrice"])))
                except Exception:
                    pass
            if strikes:
                result = sorted(strikes)
                st.session_state[cache] = result
                return result
    except Exception:
        pass
    # ATM fallback
    atm  = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)
    step = 50 if index == "NIFTY" else (100 if index == "BANKNIFTY" else 500)
    return list(range(atm - 20*step, atm + 21*step, step))


# ─────────────────────────────────────────────────────────────────────────────
# SYMBOL BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_symbol(index: str, expiry_label: str, cp: str, strike: int) -> str:
    exch = "BSE" if index in ("SENSEX", "BANKEX") else "NSE"
    code = _label_to_code(index, expiry_label).strip().upper()
    ot   = "CE" if cp.upper() in ("CE","C") else "PE"
    if any(c.isalpha() for c in code):
        return f"{exch}:{index}{code}{ot}{strike}"       # monthly
    yy, mm, dd = code[:2], str(int(code[2:4])), code[4:6]
    return f"{exch}:{index}{yy}{mm}{dd}{ot}{strike}"     # weekly


# ─────────────────────────────────────────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, interval=1, date_str=None) -> pd.DataFrame:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    fyers = get_fyers_client()
    resp  = fyers.history(data={
        "symbol": symbol, "resolution": str(interval),
        "date_format": "1", "range_from": date_str,
        "range_to": date_str, "cont_flag": "1"})
    if resp.get("s") != "ok" or not resp.get("candles"):
        return pd.DataFrame()
    df = pd.DataFrame(resp["candles"],
                      columns=["ts","open","high","low","close","volume"])
    df["time"] = (pd.to_datetime(df["ts"], unit="s")
                  .dt.tz_localize("UTC")
                  .dt.tz_convert("Asia/Kolkata")
                  .dt.tz_localize(None))
    return df.drop(columns=["ts"]).set_index("time")


def _get_candles(index, strike, expiry_label, cp, interval=1, date_str=None):
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    df  = _fetch_candles(sym, interval, date_str)
    if df.empty:
        raise ValueError(f"No candle data for {sym}. "
                         "Check date is a trading day and contract was active.")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# LIVE QUOTE
# ─────────────────────────────────────────────────────────────────────────────

def _quote(symbol: str) -> dict:
    fyers = get_fyers_client()
    resp  = fyers.quotes(data={"symbols": symbol})
    if resp.get("s") != "ok":
        raise ValueError(f"Quote failed for {symbol}: {resp}")
    v   = resp["d"][0]["v"]
    ltp = float(v.get("lp", 0))
    return {"ltp": ltp,
            "bid": float(v.get("bid", ltp*.998)),
            "ask": float(v.get("ask", ltp*1.002)),
            "prev_close": float(v.get("prev_close_price", 0)),
            "high": float(v.get("high_price", ltp)),
            "low":  float(v.get("low_price",  ltp))}

def get_live_quote(index, strike, expiry_label, cp) -> dict:
    _validate_leg(index, strike, expiry_label, cp)
    return _quote(build_symbol(index, expiry_label, cp, strike))

def get_live_ltp(index, strike, expiry_label, cp) -> float:
    return get_live_quote(index, strike, expiry_label, cp)["ltp"]

def get_live_bid_ask_ltp(index, strike, expiry_label, cp) -> tuple:
    q = get_live_quote(index, strike, expiry_label, cp)
    return q["bid"], q["ask"], q["ltp"]

def get_spot_price(index: str) -> float:
    try:
        return _quote(_UNDERLYING_SYM.get(index, f"NSE:{index}-INDEX"))["ltp"]
    except Exception:
        return {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _validate_leg(index, strike, expiry, cp):
    if not index:           raise ValueError("Index not selected.")
    if not expiry:          raise ValueError(f"Expiry not selected for {index}.")
    if not strike or strike <= 0: raise ValueError(f"Invalid strike {strike}.")
    if cp not in ("CE","PE"): raise ValueError(f"cp must be CE or PE, got {cp}.")

def validate_legs(legs: list):
    if not legs: raise ValueError("No legs.")
    for i, leg in enumerate(legs):
        try:
            _validate_leg(leg.get("index",""), leg.get("strike",0),
                          leg.get("expiry",""), leg.get("cp",""))
        except ValueError as e:
            raise ValueError(f"Leg {i+1}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SPREAD OHLCV
# ─────────────────────────────────────────────────────────────────────────────

def get_live_spread_ohlcv(legs, interval=1, date_str=None) -> pd.DataFrame:
    validate_legs(legs)
    spread = base = None
    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"],
                              leg["expiry"], leg["cp"], interval, date_str)
        price = df["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price
        if spread is None:
            spread, base = price, df.index
        else:
            spread = spread.reindex(base).add(price.reindex(base), fill_value=0)
    out = pd.DataFrame({"close": spread.values}, index=base)
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open","close"]].max(axis=1)
    out["low"]   = out[["open","close"]].min(axis=1)
    out = out.reset_index()
    if "index" in out.columns:
        out = out.rename(columns={"index": "time"})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BLACK-SCHOLES
# ─────────────────────────────────────────────────────────────────────────────

def _ncdf(x):
    return (1 + math.erf(x/math.sqrt(2)))/2

def _npdf(x):
    return math.exp(-.5*x*x)/math.sqrt(2*math.pi)

def bs_price(S,K,T,r,sig,cp):
    if T<=0 or sig<=0: return max(0.,(S-K) if cp=="CE" else (K-S))
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    return S*_ncdf(d1)-K*math.exp(-r*T)*_ncdf(d2) if cp=="CE" else K*math.exp(-r*T)*_ncdf(-d2)-S*_ncdf(-d1)

def implied_volatility(mp,S,K,T,r,cp):
    if mp<=0 or S<=0 or K<=0 or T<=0: return 0.
    lo,hi=.001,5.
    for _ in range(200):
        mid=( lo+hi)/2; p=bs_price(S,K,T,r,mid,cp)
        if abs(p-mp)<1e-5: return mid
        lo,hi=(mid,hi) if p<mp else (lo,mid)
    return mid

def bs_greeks(S,K,T,r,sig,cp):
    if T<=0 or sig<=0: return {"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sig*100}
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    pdf=_npdf(d1); g=pdf/(S*sig*math.sqrt(T)); v=S*pdf*math.sqrt(T)/100
    d=_ncdf(d1) if cp=="CE" else _ncdf(d1)-1
    t=(-(S*pdf*sig)/(2*math.sqrt(T)) + (-r*K*math.exp(-r*T)*_ncdf(d2) if cp=="CE"
       else r*K*math.exp(-r*T)*_ncdf(-d2)))/365
    return {"delta":round(d,4),"gamma":round(g,6),
            "vega":round(v,4),"theta":round(t,4),"iv":round(sig*100,2)}

def get_spread_greeks(legs,spots):
    validate_legs(legs)
    net={"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"ivs":[]}
    for leg in legs:
        try:
            S=float(spots.get(leg["index"],22800)); K=float(leg["strike"])
            T=_dte(leg["expiry"],leg["index"])
            ltp=get_live_ltp(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
            sig=implied_volatility(ltp,S,K,T,RISK_FREE_RATE,leg["cp"])
            g=bs_greeks(S,K,T,RISK_FREE_RATE,sig,leg["cp"])
            sign=1 if leg["bs"]=="Buy" else -1; ratio=leg["ratio"]
            for k in ("delta","gamma","vega","theta"): net[k]+=sign*ratio*g[k]
            net["ivs"].append(g["iv"])
        except Exception: pass
    return {"delta":round(net["delta"],4),"gamma":round(net["gamma"],6),
            "vega":round(net["vega"],4),"theta":round(net["theta"],4),
            "net_iv":round(sum(net["ivs"])/len(net["ivs"]),2) if net["ivs"] else 0.}


# ─────────────────────────────────────────────────────────────────────────────
# IV SERIES  /  MULTIPLIER
# ─────────────────────────────────────────────────────────────────────────────

def get_iv_series_live(index,strike,expiry_label,cp,tf_minutes=5,date_str=None):
    _validate_leg(index,strike,expiry_label,cp)
    df=_get_candles(index,strike,expiry_label,cp,tf_minutes,date_str)
    spot=get_spot_price(index); T=_dte(expiry_label,index); rows=[]
    for ts,row in df.iterrows():
        try: iv=implied_volatility(row["close"],spot,strike,T,RISK_FREE_RATE,cp); rows.append({"time":ts,"iv_pct":round(iv*100,2)})
        except Exception: rows.append({"time":ts,"iv_pct":0.})
    return pd.DataFrame(rows)

def get_multiplier_series_live(sx_strike,sx_expiry,n_strike,n_expiry,interval=1,date_str=None):
    for i,s,e,c in [("SENSEX",sx_strike,sx_expiry,"CE"),("SENSEX",sx_strike,sx_expiry,"PE"),
                    ("NIFTY",n_strike,n_expiry,"CE"),("NIFTY",n_strike,n_expiry,"PE")]:
        _validate_leg(i,s,e,c)
    sx_ce=_get_candles("SENSEX",sx_strike,sx_expiry,"CE",interval,date_str)["close"]
    sx_pe=_get_candles("SENSEX",sx_strike,sx_expiry,"PE",interval,date_str)["close"]
    n_ce =_get_candles("NIFTY", n_strike, n_expiry, "CE",interval,date_str)["close"]
    n_pe =_get_candles("NIFTY", n_strike, n_expiry, "PE",interval,date_str)["close"]
    sx_s=sx_strike+sx_ce-sx_pe; n_s=n_strike+n_ce-n_pe; mult=(sx_s/n_s).round(4)
    return pd.DataFrame({"time":sx_s.index,"multiplier":mult.values,
                         "sx_synth":sx_s.values.round(2),"n_synth":n_s.values.round(2)}).reset_index(drop=True)

# Re-export for data_helpers
_days_to_expiry = _dte
