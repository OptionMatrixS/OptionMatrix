"""
fyers_client.py — Option Matrix
================================
TWO auth modes — checked in this order every call:

  MODE 1 (recommended): Paste today's Fyers access token in secrets
    FYERS_ACCESS_TOKEN = "eyJ0eXAiOiJKV1..."
    FYERS_CLIENT_ID    = "XXXX-100"

  MODE 2 (auto-TOTP): All 5 TOTP secrets set
    FYERS_CLIENT_ID  = "XXXX-100"
    FYERS_SECRET_KEY = "..."
    FYERS_USERNAME   = "XY12345"
    FYERS_PIN        = "1234"
    FYERS_TOTP_KEY   = "BASE32SECRET"

If FYERS_ACCESS_TOKEN is set it is ALWAYS used — TOTP is never attempted.
Token expires at end of trading day. Paste a fresh one each morning.
"""

import os, base64, hashlib, math
import streamlit as st
import pandas as pd
import requests as _req
import pyotp
from datetime import datetime, date
from collections import defaultdict
from urllib.parse import parse_qs, urlparse
from fyers_apiv3 import fyersModel

RISK_FREE_RATE = 0.065
_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}
_REDIRECT_URI = "http://127.0.0.1:8080/"


# ─────────────────────────────────────────────────────────────────────────────
# SECRETS
# ─────────────────────────────────────────────────────────────────────────────
def _s(key: str) -> str:
    """Read secret from Streamlit Cloud secrets or env var."""
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, "").strip()

def _b64(v) -> str:
    return base64.b64encode(str(v).encode()).decode()


# ─────────────────────────────────────────────────────────────────────────────
# TOKEN — simple, no nested caching
# ─────────────────────────────────────────────────────────────────────────────
def get_token() -> str:
    """
    Always checks FYERS_ACCESS_TOKEN first.
    Falls back to TOTP only if access token is NOT set.
    Never caches failures.
    """
    # ── MODE 1: Direct access token (no TOTP, no redirect URL needed) ────────
    direct = _s("FYERS_ACCESS_TOKEN")
    if direct and len(direct) > 20:
        return direct          # ← returns here, TOTP code never runs

    # ── MODE 2: TOTP auto-login ───────────────────────────────────────────────
    cid  = _s("FYERS_CLIENT_ID")
    sec  = _s("FYERS_SECRET_KEY")
    user = _s("FYERS_USERNAME")
    pin  = _s("FYERS_PIN")
    totp = _s("FYERS_TOTP_KEY")

    if not cid:
        raise RuntimeError(
            "No Fyers credentials in secrets.\n"
            "Add FYERS_ACCESS_TOKEN = 'eyJ...' in "
            "Streamlit Cloud → ⋮ → Settings → Secrets"
        )

    if not all([sec, user, pin, totp]):
        raise RuntimeError(
            "FYERS_ACCESS_TOKEN not set and TOTP secrets incomplete.\n"
            "Either paste FYERS_ACCESS_TOKEN, or set all 5 TOTP secrets."
        )

    # Check session-state token cache (avoids re-login on every rerun)
    cached = st.session_state.get("_fyers_token")
    if cached and len(cached) > 20:
        return cached

    token = _run_totp_login(cid, sec, user, pin, totp)
    st.session_state["_fyers_token"] = token
    return token


def _run_totp_login(client_id, secret_key, username, pin, totp_key) -> str:
    """
    Raw TOTP login — no Streamlit caching so failures are never stored.
    Returns access_token or raises RuntimeError.
    """
    s = _req.Session()

    # Step 1
    r1 = s.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                json={"fy_id": _b64(username), "app_id": "2"}, timeout=10)
    if r1.status_code == 429:
        raise RuntimeError("Rate limited (429). Wait 60 s then Refresh Token.")
    d1 = r1.json()
    if d1.get("s") != "ok":
        raise RuntimeError(f"Step 1 failed: {d1}")

    # Step 2
    r2 = s.post("https://api-t2.fyers.in/vagator/v2/verify_otp",
                json={"request_key": d1["request_key"],
                      "otp": pyotp.TOTP(totp_key).now()}, timeout=10)
    d2 = r2.json()
    if d2.get("s") != "ok":
        raise RuntimeError(
            f"Step 2 (TOTP) failed: {d2}\n"
            "FYERS_TOTP_KEY must be the Base32 secret from TOTP setup "
            "(e.g. JBSWY3DPEHPK3PXP) — NOT the 6-digit code."
        )

    # Step 3
    r3 = s.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
                json={"request_key": d2["request_key"],
                      "identity_type": "pin",
                      "identifier": _b64(pin)}, timeout=10)
    d3 = r3.json()
    if d3.get("s") != "ok":
        raise RuntimeError(f"Step 3 (PIN) failed: {d3} — check FYERS_PIN")

    # Step 4
    app_id = client_id.split("-")[0]
    r4 = s.post("https://api-t1.fyers.in/api/v3/token",
                json={"fyers_id": username, "app_id": app_id,
                      "redirect_uri": _REDIRECT_URI, "appType": "100",
                      "code_challenge": "", "state": "sample",
                      "scope": "", "nonce": "", "response_type": "code",
                      "create_cookie": True},
                headers={"Authorization": f"Bearer {d3['data']['access_token']}"},
                timeout=10)
    d4 = r4.json()
    if d4.get("s") != "ok":
        raise RuntimeError(
            f"Step 4 failed: {d4}\n"
            f"redirectUrl mismatch → set Redirect URL in myapi.fyers.in "
            f"to exactly: {_REDIRECT_URI}"
        )
    data = d4.get("data", {})
    auth_code = (data.get("auth")
                 or parse_qs(urlparse(d4.get("Url","")).query).get("auth_code",[None])[0]
                 or parse_qs(urlparse(data.get("url","")).query).get("auth_code",[None])[0])
    if not auth_code:
        raise RuntimeError(f"Step 4: no auth_code in {d4}")

    # Step 5
    app_hash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
    r5 = s.post("https://api-t1.fyers.in/api/v3/validate-authcode",
                json={"grant_type": "authorization_code",
                      "appIdHash": app_hash, "code": auth_code}, timeout=10)
    d5 = r5.json()
    token = d5.get("access_token")
    if not token:
        try:
            sm = fyersModel.SessionModel(
                client_id=client_id, secret_key=secret_key,
                redirect_uri=_REDIRECT_URI,
                response_type="code", grant_type="authorization_code")
            sm.set_token(auth_code)
            d5b = sm.generate_token()
            token = d5b.get("access_token")
            if not token:
                raise RuntimeError(f"Step 5 both methods failed: {d5} / {d5b}")
        except Exception as e:
            raise RuntimeError(f"Step 5 failed: {d5} / SDK: {e}")
    return token


def get_fyers_client() -> fyersModel.FyersModel:
    """Returns an authenticated FyersModel, cached in session state."""
    if st.session_state.get("_fc"):
        return st.session_state._fc
    tok = get_token()
    cid = _s("FYERS_CLIENT_ID")
    if not cid:
        raise RuntimeError("FYERS_CLIENT_ID missing from secrets.")
    fc = fyersModel.FyersModel(client_id=cid, is_async=False, token=tok, log_path="")
    st.session_state._fc = fc
    return fc


def refresh_token():
    """Clear all cached auth — forces re-auth on next call."""
    st.session_state.pop("_fc", None)
    st.session_state.pop("_fyers_token", None)
    for k in list(st.session_state.keys()):
        if k.startswith("expiries_") or k.startswith("strikes_"):
            del st.session_state[k]
    # Also clear any st.cache_resource caches
    try:
        _fetch_expiry_map.clear()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRIES
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(ttl=1800)
def _fetch_expiry_map(token: str, cid: str, sym: str) -> dict:
    """Fetch and cache expiry map for one symbol. Raises on failure so empty results are NOT cached."""
    fyers = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
    resp  = fyers.optionchain(data={"symbol": sym, "strikecount": 1, "timestamp": ""})
    if not (resp and resp.get("s") == "ok"):
        raise RuntimeError(f"optionchain failed: {resp}")
    raw = resp.get("data", {}).get("expiryData", [])
    parsed = []
    for e in raw:
        if not isinstance(e, dict): continue
        try:
            dd, mm, yy4 = e["date"].split("-")
            dd, mm, yy4 = int(dd), int(mm), int(yy4)
        except Exception:
            continue
        parsed.append((yy4 % 100, mm, dd, _MONTHS[mm-1]))
    if not parsed:
        raise RuntimeError(f"No expiry dates parsed from response for {sym}")
    by_month = defaultdict(list)
    for yy, mm, dd, mon in parsed:
        by_month[(yy, mm)].append(dd)
    last_day = {k: max(v) for k, v in by_month.items()}
    result = {}
    for yy, mm, dd, mon in parsed:
        is_m  = (dd == last_day[(yy, mm)])
        code  = f"{yy:02d}{mon}" if is_m else f"{yy:02d}{mm:02d}{dd:02d}"
        label = f"{dd:02d} {mon} {yy:02d} ({'M' if is_m else 'W'})"
        result[label] = code
    return result


def get_expiries(index: str) -> list:
    ck = f"expiries_{index}"
    if st.session_state.get(ck):
        return list(st.session_state[ck].keys())
    tok  = get_token()
    cid  = _s("FYERS_CLIENT_ID")
    sym  = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
    try:
        data = _fetch_expiry_map(tok, cid, sym)
    except Exception as e:
        # Clear the cache so next call retries fresh
        try: _fetch_expiry_map.clear()
        except Exception: pass
        raise ValueError(
            f"Load expiries failed for {index}: {e}\n"
            "Make sure FYERS_ACCESS_TOKEN is today's token. "
            "Click 🔄 Refresh Token in sidebar."
        )
    if not data:
        try: _fetch_expiry_map.clear()
        except Exception: pass
        raise ValueError(
            f"No expiries returned for {index}.\n"
            "Make sure FYERS_ACCESS_TOKEN is today's token. "
            "Click 🔄 Refresh Token in sidebar."
        )
    st.session_state[ck] = data
    return list(data.keys())


def _label_to_code(index: str, label: str) -> str:
    return st.session_state.get(f"expiries_{index}", {}).get(label, label)


def _code_to_date(code: str) -> date:
    import calendar
    code = code.strip().upper()
    mmap = {m: i+1 for i, m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):
        yy = int(code[:2]); mon = code[2:5]; mm = mmap[mon]
        return date(2000+yy, mm, calendar.monthrange(2000+yy, mm)[1])
    return date(2000+int(code[:2]), int(code[2:4]), int(code[4:6]))


def _dte(label: str, index: str = "") -> float:
    try:
        code = _label_to_code(index, label) if index else label
        return max((_code_to_date(code) - datetime.now().date()).days, 1) / 365.0
    except Exception:
        return 30 / 365.0

_days_to_expiry = _dte


# ─────────────────────────────────────────────────────────────────────────────
# STRIKES — ALL strikes via strikecount:0
# ─────────────────────────────────────────────────────────────────────────────
def get_strikes(index: str, expiry_label: str) -> list:
    code = _label_to_code(index, expiry_label)
    ck   = f"strikes_{index}_{code}"
    if st.session_state.get(ck):
        return st.session_state[ck]
    try:
        fyers = get_fyers_client()
        sym   = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
        resp  = fyers.optionchain(data={"symbol": sym, "strikecount": 0, "timestamp": ""})
        if resp and resp.get("s") == "ok":
            strikes = sorted({
                int(float(o["strikePrice"]))
                for o in resp.get("data", {}).get("optionsChain", [])
                if isinstance(o, dict) and o.get("strikePrice")
            })
            if strikes:
                st.session_state[ck] = strikes
                return strikes
    except Exception:
        pass
    atm  = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)
    step = 50 if index == "NIFTY" else (100 if index == "BANKNIFTY" else 500)
    return list(range(atm - 40*step, atm + 41*step, step))


# ─────────────────────────────────────────────────────────────────────────────
# SYMBOL BUILDER
# ─────────────────────────────────────────────────────────────────────────────
def build_symbol(index: str, expiry_label: str, cp: str, strike: int) -> str:
    exch = "BSE" if index in ("SENSEX", "BANKEX") else "NSE"
    code = _label_to_code(index, expiry_label).strip().upper()
    ot   = "CE" if cp.upper() in ("CE", "C") else "PE"
    if any(c.isalpha() for c in code):
        return f"{exch}:{index}{code}{ot}{strike}"
    yy, mm, dd = code[:2], str(int(code[2:4])), code[4:6]
    return f"{exch}:{index}{yy}{mm}{dd}{ot}{strike}"


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
    return {
        "ltp":        ltp,
        "bid":        float(v.get("bid",              ltp * 0.998)),
        "ask":        float(v.get("ask",              ltp * 1.002)),
        "prev_close": float(v.get("prev_close_price", 0)),
        "high":       float(v.get("high_price",       ltp)),
        "low":        float(v.get("low_price",        ltp)),
    }

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
# CANDLES with live-quote fallback
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_candles(symbol: str, interval: int = 1, date_str: str = None) -> pd.DataFrame:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    fyers = get_fyers_client()
    resp  = fyers.history(data={
        "symbol": symbol, "resolution": str(interval),
        "date_format": "1", "range_from": date_str,
        "range_to": date_str, "cont_flag": "1"})
    if resp.get("s") != "ok" or not resp.get("candles"):
        return pd.DataFrame()
    df = pd.DataFrame(resp["candles"], columns=["ts","open","high","low","close","volume"])
    df["time"] = (pd.to_datetime(df["ts"], unit="s")
                  .dt.tz_localize("UTC")
                  .dt.tz_convert("Asia/Kolkata")
                  .dt.tz_localize(None))
    return df.drop(columns=["ts"]).set_index("time")


def _get_candles(index, strike, expiry_label, cp, interval=1, date_str=None) -> pd.DataFrame:
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    df  = _fetch_candles(sym, interval, date_str)
    if df.empty:
        try:
            q = _quote(sym); ltp = q["ltp"]
            now = pd.Timestamp.now().floor("min")
            df  = pd.DataFrame(
                {"open":[ltp],"high":[ltp],"low":[ltp],"close":[ltp],"volume":[0]},
                index=[now])
            df.index.name = "time"
        except Exception:
            raise ValueError(f"No data for {sym}. Token may be expired or market closed.")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────
def _validate_leg(index, strike, expiry, cp):
    if not index:                 raise ValueError("Index not selected.")
    if not expiry:                raise ValueError(f"Expiry not selected for {index}.")
    if not strike or strike <= 0: raise ValueError(f"Invalid strike: {strike}.")
    if cp not in ("CE", "PE"):    raise ValueError(f"cp must be CE or PE, got: {cp}.")

def validate_legs(legs: list):
    if not legs: raise ValueError("No legs provided.")
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
        df    = _get_candles(leg["index"], leg["strike"], leg["expiry"],
                             leg["cp"], interval, date_str)
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
def _ncdf(x): return (1 + math.erf(x / math.sqrt(2))) / 2
def _npdf(x): return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def bs_price(S, K, T, r, sig, cp):
    if T <= 0 or sig <= 0:
        return max(0., (S-K) if cp == "CE" else (K-S))
    d1 = (math.log(S/K) + (r + 0.5*sig**2)*T) / (sig*math.sqrt(T))
    d2 = d1 - sig*math.sqrt(T)
    return (S*_ncdf(d1) - K*math.exp(-r*T)*_ncdf(d2) if cp == "CE"
            else K*math.exp(-r*T)*_ncdf(-d2) - S*_ncdf(-d1))

def implied_volatility(mp, S, K, T, r, cp):
    if mp <= 0 or S <= 0 or K <= 0 or T <= 0: return 0.
    lo, hi = 0.001, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2; p = bs_price(S, K, T, r, mid, cp)
        if abs(p - mp) < 1e-5: return mid
        lo, hi = (mid, hi) if p < mp else (lo, mid)
    return mid

def bs_greeks(S, K, T, r, sig, cp):
    if T <= 0 or sig <= 0:
        return {"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sig*100}
    d1  = (math.log(S/K) + (r+0.5*sig**2)*T) / (sig*math.sqrt(T))
    d2  = d1 - sig*math.sqrt(T)
    pdf = _npdf(d1)
    g   = pdf / (S * sig * math.sqrt(T))
    v   = S * pdf * math.sqrt(T) / 100
    d   = _ncdf(d1) if cp == "CE" else _ncdf(d1) - 1
    t   = (-(S*pdf*sig)/(2*math.sqrt(T))
           + (-r*K*math.exp(-r*T)*_ncdf(d2) if cp == "CE"
              else  r*K*math.exp(-r*T)*_ncdf(-d2))) / 365
    return {"delta":round(d,4),"gamma":round(g,6),
            "vega":round(v,4), "theta":round(t,4),"iv":round(sig*100,2)}

def get_spread_greeks(legs, spots):
    validate_legs(legs)
    net = {"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"ivs":[]}
    for leg in legs:
        try:
            S   = float(spots.get(leg["index"], 22800))
            K   = float(leg["strike"])
            T   = _dte(leg["expiry"], leg["index"])
            ltp = get_live_ltp(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
            sig = implied_volatility(ltp, S, K, T, RISK_FREE_RATE, leg["cp"])
            g   = bs_greeks(S, K, T, RISK_FREE_RATE, sig, leg["cp"])
            sgn = 1 if leg["bs"] == "Buy" else -1
            for k in ("delta","gamma","vega","theta"):
                net[k] += sgn * leg["ratio"] * g[k]
            net["ivs"].append(g["iv"])
        except Exception:
            pass
    return {
        "delta":  round(net["delta"],  4),
        "gamma":  round(net["gamma"],  6),
        "vega":   round(net["vega"],   4),
        "theta":  round(net["theta"],  4),
        "net_iv": round(sum(net["ivs"])/len(net["ivs"]), 2) if net["ivs"] else 0.,
    }


# ─────────────────────────────────────────────────────────────────────────────
# IV SERIES
# ─────────────────────────────────────────────────────────────────────────────
def get_iv_series_live(index, strike, expiry_label, cp, tf_minutes=5, date_str=None):
    _validate_leg(index, strike, expiry_label, cp)
    df   = _get_candles(index, strike, expiry_label, cp, tf_minutes, date_str)
    spot = get_spot_price(index)
    T    = _dte(expiry_label, index)
    rows = []
    for ts, row in df.iterrows():
        try:
            iv = implied_volatility(row["close"], spot, strike, T, RISK_FREE_RATE, cp)
        except Exception:
            iv = 0.
        rows.append({"time": ts, "iv_pct": round(iv * 100, 2)})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# MULTIPLIER — candle-based with live-quote fallback
# ─────────────────────────────────────────────────────────────────────────────
def get_multiplier_series_live(sx_strike, sx_expiry, n_strike, n_expiry,
                                interval=1, date_str=None) -> pd.DataFrame:
    try:
        sx_ce = _get_candles("SENSEX",sx_strike,sx_expiry,"CE",interval,date_str)["close"]
        sx_pe = _get_candles("SENSEX",sx_strike,sx_expiry,"PE",interval,date_str)["close"]
        n_ce  = _get_candles("NIFTY", n_strike, n_expiry, "CE",interval,date_str)["close"]
        n_pe  = _get_candles("NIFTY", n_strike, n_expiry, "PE",interval,date_str)["close"]
        common = (sx_ce.index.intersection(sx_pe.index)
                             .intersection(n_ce.index)
                             .intersection(n_pe.index))
        if len(common) > 0:
            sx_s = sx_strike + sx_ce[common] - sx_pe[common]
            n_s  = n_strike  + n_ce[common]  - n_pe[common]
            mult = (sx_s / n_s).round(4)
            return pd.DataFrame({
                "time":       common,
                "multiplier": mult.values,
                "sx_synth":   sx_s.values.round(2),
                "n_synth":    n_s.values.round(2),
            }).reset_index(drop=True)
    except Exception:
        pass

    # Fallback: single point from live quotes
    try:
        sx_ce_q = _quote(build_symbol("SENSEX",sx_expiry,"CE",sx_strike))["ltp"]
        sx_pe_q = _quote(build_symbol("SENSEX",sx_expiry,"PE",sx_strike))["ltp"]
        n_ce_q  = _quote(build_symbol("NIFTY", n_expiry, "CE",n_strike))["ltp"]
        n_pe_q  = _quote(build_symbol("NIFTY", n_expiry, "PE",n_strike))["ltp"]
        sx_s = sx_strike + sx_ce_q - sx_pe_q
        n_s  = n_strike  + n_ce_q  - n_pe_q
        mult = round(sx_s / n_s, 4) if n_s != 0 else 0.
        return pd.DataFrame({
            "time":       [pd.Timestamp.now().floor("min")],
            "multiplier": [mult],
            "sx_synth":   [round(sx_s, 2)],
            "n_synth":    [round(n_s,  2)],
        })
    except Exception as e:
        raise ValueError(
            f"Multiplier failed: {e}\n"
            "Check expiry/strike and that your token is today's."
        )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN DEBUG PANEL
# ─────────────────────────────────────────────────────────────────────────────
def render_debug_panel():
    with st.expander("🔧 Debug", expanded=False):
        if st.button("Clear All Caches", key="dbg_clear"):
            refresh_token()
            st.rerun()
        direct = _s("FYERS_ACCESS_TOKEN")
        if direct:
            st.success(f"✓ Direct token: {direct[:25]}…")
            st.caption("Using FYERS_ACCESS_TOKEN — TOTP is disabled.")
        else:
            st.warning("No FYERS_ACCESS_TOKEN — will try TOTP")
            try:
                tok = get_token()
                st.success(f"✓ TOTP token: {tok[:25]}…")
            except Exception as e:
                st.error(f"Token error: {e}")
