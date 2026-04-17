"""
fyers_client.py
───────────────
Fyers API v3 — TOTP auto-login for Streamlit Cloud.

Secrets in Streamlit Cloud → Settings → Secrets:
  FYERS_CLIENT_ID  = "YOURAPP-100"
  FYERS_SECRET_KEY = "YOURSECRET"
  FYERS_USERNAME   = "YOURID"
  FYERS_PIN        = "1234"
  FYERS_TOTP_KEY   = "YOURBASE32SECRET"

Optional (skips TOTP entirely, paste from myapi.fyers.in → Generate Token):
  FYERS_ACCESS_TOKEN = "eyJ..."
"""

import os, base64, math
import streamlit as st
import pandas as pd
from datetime import datetime, date
from collections import defaultdict
from urllib.parse import parse_qs, urlparse
import requests as _requests

try:
    import pyotp
except ImportError:
    raise ImportError("pip install pyotp")

try:
    from fyers_apiv3 import fyersModel
except ImportError:
    raise ImportError("pip install fyers-apiv3")

RISK_FREE_RATE = 0.065

# ── REDIRECT URI ──────────────────────────────────────────────────────────────
# Must match EXACTLY what is set in your Fyers API dashboard.
# Go to: myapi.fyers.in → Apps → your app → Edit → Redirect URL
# Default Fyers dashboard value is:
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"
# If you changed it to http://127.0.0.1:8080/ in dashboard, change the line above too.

_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}
_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN",
           "JUL","AUG","SEP","OCT","NOV","DEC"]


# ── helpers ────────────────────────────────────────────────────────────────────

def _s(key: str) -> str:
    """Read secret from Streamlit secrets or environment variable."""
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, "")


def _b64(v) -> str:
    return base64.b64encode(str(v).encode()).decode()


def _safe_json(r, step: str) -> dict:
    raw = r.text.strip()
    if not raw:
        raise ValueError(f"{step}: empty response (HTTP {r.status_code})")
    try:
        return r.json()
    except Exception:
        raise ValueError(f"{step}: non-JSON body: {raw[:200]}")


# ── TOTP auto-login ────────────────────────────────────────────────────────────
# Pattern proven working with Fyers API v3:
#   Step 1: send_login_otp_v2  (fy_id = base64)
#   Step 2: verify_otp         (TOTP 6-digit)
#   Step 3: verify_pin_v2      (pin = base64)
#   Step 4: api-t1 token       (get auth_code URL)  ← SessionModel created HERE
#   Step 5: generate_token()   (exchange auth_code immediately)

def _generate_token() -> tuple:
    """Returns (access_token, None) on success or (None, error_str) on failure."""
    cid      = _s("FYERS_CLIENT_ID")
    secret   = _s("FYERS_SECRET_KEY")
    username = _s("FYERS_USERNAME")
    pin      = _s("FYERS_PIN")
    totp_key = _s("FYERS_TOTP_KEY")

    missing = [k for k, v in {
        "FYERS_CLIENT_ID": cid, "FYERS_SECRET_KEY": secret,
        "FYERS_USERNAME": username, "FYERS_PIN": pin,
        "FYERS_TOTP_KEY": totp_key,
    }.items() if not v]
    if missing:
        return None, f"Missing secrets: {', '.join(missing)}"

    try:
        s = _requests.Session()
        s.headers.update({
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/112.0.0.0 Safari/537.36",
        })

        # Step 1 — send OTP
        r1  = s.post(
            "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
            json={"fy_id": _b64(username), "app_id": "2"}, timeout=15)
        d1  = _safe_json(r1, "Step1/send_otp")
        if d1.get("s") != "ok":
            return None, f"Step1 failed: {d1}"

        # Step 2 — verify TOTP
        r2  = s.post(
            "https://api-t2.fyers.in/vagator/v2/verify_otp",
            json={"request_key": d1["request_key"],
                  "otp": pyotp.TOTP(totp_key).now()}, timeout=15)
        d2  = _safe_json(r2, "Step2/verify_totp")
        if d2.get("s") != "ok":
            return None, (f"Step2 TOTP failed: {d2}. "
                          "FYERS_TOTP_KEY must be the Base32 secret "
                          "from authenticator setup, NOT the 6-digit code.")

        # Step 3 — verify PIN (base64 per vagator v2 spec)
        r3  = s.post(
            "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
            json={"request_key": d2["request_key"],
                  "identity_type": "pin",
                  "identifier": _b64(pin)}, timeout=15)
        d3  = _safe_json(r3, "Step3/verify_pin")
        if d3.get("s") != "ok":
            return None, f"Step3 PIN failed: {d3}. Check FYERS_PIN."

        bearer = d3["data"]["access_token"]
        app_id = cid.split("-")[0]

        # Step 4 — create SessionModel FIRST, then get auth_code
        # This is the critical fix: SessionModel must exist before the
        # auth_code is issued so it can exchange it with zero delay.
        session = fyersModel.SessionModel(
            client_id=cid,
            secret_key=secret,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code",
        )

        r4 = s.post(
            "https://api-t1.fyers.in/api/v3/token",
            json={
                "fyers_id":       username,
                "app_id":         app_id,
                "redirect_uri":   REDIRECT_URI,
                "appType":        "100",
                "code_challenge": "",
                "state":          "abcdefg",
                "scope":          "",
                "nonce":          "",
                "response_type":  "code",
                "create_cookie":  True,
            },
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=15,
        )
        d4 = _safe_json(r4, "Step4/get_auth_code")
        if d4.get("s") != "ok":
            return None, (
                f"Step4 failed: {d4}\n"
                f"IMPORTANT: Redirect URL in Fyers dashboard must be EXACTLY:\n"
                f"  {REDIRECT_URI}"
            )

        auth_code = parse_qs(urlparse(d4["Url"]).query).get("auth_code", [None])[0]
        if not auth_code:
            return None, f"No auth_code in URL: {d4.get('Url','')}"

        # Step 5 — exchange auth_code immediately (same session object)
        session.set_token(auth_code)
        d5    = session.generate_token()
        token = d5.get("access_token")
        if not token:
            return None, f"Step5 failed: {d5}"

        return token, None

    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── cached shared token ────────────────────────────────────────────────────────
# IMPORTANT: @st.cache_resource only caches SUCCESSFUL returns.
# If _generate_token() fails, RuntimeError is raised (not cached),
# so the next page load retries a fresh login automatically.

@st.cache_resource
def _get_shared_token() -> str:
    """
    Token priority:
      1. FYERS_ACCESS_TOKEN in Streamlit secrets  → fastest, paste from myapi.fyers.in
      2. fyers_token.txt on disk                  → local dev convenience
      3. TOTP auto-login                          → fully automated
    """
    # Option 1: direct token in secrets
    direct = _s("FYERS_ACCESS_TOKEN")
    if direct and len(direct) > 20:
        return direct

    # Option 2: token file (local dev only)
    try:
        tok = open("fyers_token.txt").read().strip()
        if tok and len(tok) > 20:
            return tok
    except FileNotFoundError:
        pass

    # Option 3: TOTP auto-login
    token, err = _generate_token()
    if token:
        return token

    # Raise RuntimeError so st.cache_resource does NOT cache this failure.
    # Next user action will retry from scratch.
    raise RuntimeError(
        f"Fyers login failed: {err}\n\n"
        f"FASTEST FIX: Add to Streamlit Cloud secrets:\n"
        f'  FYERS_ACCESS_TOKEN = "paste_token_from_myapi.fyers.in"\n\n'
        f"OR ensure Redirect URL in Fyers dashboard is exactly:\n"
        f"  {REDIRECT_URI}"
    )


def get_fyers_client() -> fyersModel.FyersModel:
    """Authenticated Fyers client, cached per Streamlit session."""
    if st.session_state.get("fyers_client"):
        return st.session_state.fyers_client
    client = fyersModel.FyersModel(
        client_id=_s("FYERS_CLIENT_ID"),
        token=_get_shared_token(),
        log_path="",
    )
    st.session_state.fyers_client = client
    return client


def refresh_token():
    """Force re-auth. Called from sidebar Refresh Token button."""
    _get_shared_token.clear()
    for k in list(st.session_state.keys()):
        if k in ("fyers_client",) or \
           k.startswith("expiries_") or k.startswith("strikes_"):
            st.session_state.pop(k, None)


# ── expiries ───────────────────────────────────────────────────────────────────

def _fyers_sym_for(index: str) -> str:
    return _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")


@st.cache_resource
def _fetch_expiry_codes(token: str, fyers_sym: str) -> dict:
    try:
        fyers = fyersModel.FyersModel(
            client_id=_s("FYERS_CLIENT_ID"), token=token, log_path="")
        resp  = fyers.optionchain(
            data={"symbol": fyers_sym, "strikecount": 5, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            return {}
        parsed = []
        for e in resp.get("data", {}).get("expiryData", []):
            if not isinstance(e, dict):
                continue
            try:
                dd, mm, yyyy = (int(x) for x in e["date"].split("-"))
                parsed.append((yyyy % 100, mm, dd, _MONTHS[mm - 1]))
            except Exception:
                continue
        by_month = defaultdict(list)
        for yy, mm, dd, mon in parsed:
            by_month[(yy, mm)].append(dd)
        last_dd = {k: max(v) for k, v in by_month.items()}
        result  = {}
        for yy, mm, dd, mon in parsed:
            if dd == last_dd[(yy, mm)]:
                code  = f"{yy:02d}{mon}"
                label = f"{dd:02d} {mon} {yy:02d} (M)"
            else:
                code  = f"{yy:02d}{mm:02d}{dd:02d}"
                label = f"{dd:02d} {mon} {yy:02d} (W)"
            result[label] = code
        return result
    except Exception:
        return {}


def get_expiries(index: str) -> list:
    key = f"expiries_{index}"
    if st.session_state.get(key):
        return list(st.session_state[key].keys())
    codes = _fetch_expiry_codes(_get_shared_token(), _fyers_sym_for(index))
    if not codes:
        raise ValueError(f"No expiries returned for {index}.")
    st.session_state[key] = codes
    return list(codes.keys())


def _expiry_label_to_code(index: str, label: str) -> str:
    return st.session_state.get(f"expiries_{index}", {}).get(label, label)


def _expiry_code_to_date(code: str) -> date:
    import calendar as _cal
    code   = code.strip().upper()
    months = {m: i + 1 for i, m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):
        yy, mon = int(code[:2]), code[2:5]
        mm = months.get(mon, 3)
        return date(2000 + yy, mm, _cal.monthrange(2000 + yy, mm)[1])
    return date(2000 + int(code[0:2]), int(code[2:4]), int(code[4:6]))


def _days_to_expiry(label: str, index: str = "") -> float:
    try:
        code = _expiry_label_to_code(index, label) if index else label
        days = (_expiry_code_to_date(code) - datetime.now().date()).days
        return max(days, 1) / 365.0
    except Exception:
        return 30 / 365.0


# ── strikes ────────────────────────────────────────────────────────────────────

def get_strikes(index: str, expiry_label: str) -> list:
    code = _expiry_label_to_code(index, expiry_label)
    key  = f"strikes_{index}_{code}"
    if st.session_state.get(key):
        return st.session_state[key]
    try:
        resp = get_fyers_client().optionchain(
            data={"symbol": _fyers_sym_for(index),
                  "strikecount": 50, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            raise ValueError(resp)
        strikes = sorted({
            int(float(o["strikePrice"]))
            for o in resp.get("data", {}).get("optionsChain", [])
            if isinstance(o, dict) and "strikePrice" in o
        })
        if not strikes:
            raise ValueError("empty")
        st.session_state[key] = strikes
        return strikes
    except Exception:
        atm  = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)
        step = 50 if index == "NIFTY" else (100 if index == "BANKNIFTY" else 500)
        return list(range(atm - 20 * step, atm + 21 * step, step))


# ── symbol builder ─────────────────────────────────────────────────────────────

def _exchange_for(index: str) -> str:
    return "BSE" if index in ("SENSEX", "BANKEX") else "NSE"


def build_symbol(index: str, expiry_label: str, cp: str, strike: int) -> str:
    exchange = _exchange_for(index)
    code     = _expiry_label_to_code(index, expiry_label).strip().upper()
    ot       = "CE" if cp.upper() in ("CE", "C") else "PE"
    if any(c.isalpha() for c in code):          # monthly e.g. 26MAR
        return f"{exchange}:{index}{code}{ot}{strike}"
    yy, mm, dd = code[0:2], str(int(code[2:4])), code[4:6]
    return f"{exchange}:{index}{yy}{mm}{dd}{ot}{strike}"


# ── candles ────────────────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, interval: int = 1,
                   date_str: str = None) -> pd.DataFrame:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    resp = get_fyers_client().history(data={
        "symbol": symbol, "resolution": str(interval),
        "date_format": "1", "range_from": date_str,
        "range_to": date_str, "cont_flag": "1",
    })
    if resp.get("s") != "ok" or not resp.get("candles"):
        return pd.DataFrame()
    df = pd.DataFrame(resp["candles"],
                      columns=["timestamp","open","high","low","close","volume"])
    df["time"] = (pd.to_datetime(df["timestamp"], unit="s")
                  .dt.tz_localize("UTC")
                  .dt.tz_convert("Asia/Kolkata")
                  .dt.tz_localize(None))
    df = df.drop(columns=["timestamp"]).set_index("time")
    return df[~df.index.duplicated(keep="last")]


def _get_candles(index: str, strike: int, expiry_label: str,
                 cp: str, interval: int = 1,
                 date_str: str = None) -> pd.DataFrame:
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    df  = _fetch_candles(sym, interval, date_str)
    if df.empty:
        raise ValueError(f"No candle data for {sym}.")
    return df


# ── live quote ─────────────────────────────────────────────────────────────────

def _get_live_quote_fyers(symbol: str) -> dict:
    resp = get_fyers_client().quotes(data={"symbols": symbol})
    if resp.get("s") != "ok":
        raise ValueError(f"Quote failed for {symbol}: {resp}")
    d   = resp["d"][0]["v"]
    ltp = float(d.get("lp", 0))
    return {
        "ltp":        ltp,
        "bid":        float(d.get("bid",   ltp * 0.998)),
        "ask":        float(d.get("ask",   ltp * 1.002)),
        "prev_close": float(d.get("prev_close_price", 0)),
        "high":       float(d.get("high_price", ltp)),
        "low":        float(d.get("low_price",  ltp)),
    }


def get_live_quote(index, strike, expiry_label, cp) -> dict:
    _validate_leg(index, strike, expiry_label, cp)
    return _get_live_quote_fyers(build_symbol(index, expiry_label, cp, strike))

def get_live_ltp(index, strike, expiry_label, cp) -> float:
    return get_live_quote(index, strike, expiry_label, cp)["ltp"]

def get_live_bid_ask_ltp(index, strike, expiry_label, cp) -> tuple:
    q = get_live_quote(index, strike, expiry_label, cp)
    return q["bid"], q["ask"], q["ltp"]

def get_spot_price(index: str) -> float:
    try:
        return _get_live_quote_fyers(_fyers_sym_for(index))["ltp"]
    except Exception:
        return {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)


# ── validation ─────────────────────────────────────────────────────────────────

def _validate_leg(index, strike, expiry, cp):
    if not index:
        raise ValueError("Index not selected.")
    if not expiry or not expiry.strip():
        raise ValueError(f"Expiry not selected for {index}.")
    if not isinstance(strike, (int, float)) or strike <= 0:
        raise ValueError(f"Invalid strike '{strike}'.")
    if cp not in ("CE", "PE"):
        raise ValueError(f"Invalid option type '{cp}'.")

def validate_legs(legs: list):
    if not legs:
        raise ValueError("No legs provided.")
    for i, leg in enumerate(legs):
        try:
            _validate_leg(leg.get("index",""), leg.get("strike",0),
                          leg.get("expiry",""), leg.get("cp",""))
        except ValueError as e:
            raise ValueError(f"Leg {i+1}: {e}")


# ── spread OHLCV ───────────────────────────────────────────────────────────────

def get_live_spread_ohlcv(legs: list, interval: int = 1,
                           date_str: str = None) -> pd.DataFrame:
    validate_legs(legs)
    spread_close = base_times = None
    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"],
                             leg["expiry"], leg["cp"], interval, date_str)
        price = df["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price
        if spread_close is None:
            spread_close, base_times = price, df.index
        else:
            spread_close = spread_close.reindex(base_times).add(
                price.reindex(base_times), fill_value=0)
    out = pd.DataFrame(index=base_times)
    out["close"] = spread_close.values
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open","close"]].max(axis=1)
    out["low"]   = out[["open","close"]].min(axis=1)
    out = out.reset_index()
    if "index" in out.columns:
        out = out.rename(columns={"index": "time"})
    return out


# ── Black-Scholes ──────────────────────────────────────────────────────────────

def _norm_cdf(x):
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0

def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def bs_price(S, K, T, r, sigma, cp):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "CE" else (K - S))
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if cp == "CE":
        return S*_norm_cdf(d1) - K*math.exp(-r*T)*_norm_cdf(d2)
    return K*math.exp(-r*T)*_norm_cdf(-d2) - S*_norm_cdf(-d1)

def implied_volatility(market_price, S, K, T, r, cp):
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
    lo, hi = 0.001, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        p   = bs_price(S, K, T, r, mid, cp)
        if abs(p - market_price) < 1e-5:
            return mid
        lo, hi = (mid, hi) if p < market_price else (lo, mid)
    return mid

def bs_greeks(S, K, T, r, sigma, cp):
    if T <= 0 or sigma <= 0:
        return {"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sigma*100}
    d1  = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2  = d1 - sigma*math.sqrt(T)
    pdf = _norm_pdf(d1)
    gamma = pdf / (S*sigma*math.sqrt(T))
    vega  = S*pdf*math.sqrt(T) / 100
    if cp == "CE":
        delta = _norm_cdf(d1)
        theta = (-(S*pdf*sigma)/(2*math.sqrt(T))
                 - r*K*math.exp(-r*T)*_norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(S*pdf*sigma)/(2*math.sqrt(T))
                 + r*K*math.exp(-r*T)*_norm_cdf(-d2)) / 365
    return {"delta":round(delta,4),"gamma":round(gamma,6),
            "vega":round(vega,4),"theta":round(theta,4),
            "iv":round(sigma*100,2)}

def get_spread_greeks(legs: list, spot_prices: dict) -> dict:
    validate_legs(legs)
    net = {"delta":0.0,"gamma":0.0,"vega":0.0,"theta":0.0,"ivs":[]}
    for leg in legs:
        try:
            S     = float(spot_prices.get(leg["index"], 22800))
            K     = float(leg["strike"])
            T     = _days_to_expiry(leg["expiry"], leg["index"])
            ltp   = get_live_ltp(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
            sigma = implied_volatility(ltp, S, K, T, RISK_FREE_RATE, leg["cp"])
            g     = bs_greeks(S, K, T, RISK_FREE_RATE, sigma, leg["cp"])
            sign  = 1 if leg["bs"] == "Buy" else -1
            r     = leg["ratio"]
            net["delta"] += sign*r*g["delta"]
            net["gamma"] += sign*r*g["gamma"]
            net["vega"]  += sign*r*g["vega"]
            net["theta"] += sign*r*g["theta"]
            net["ivs"].append(g["iv"])
        except Exception:
            pass
    return {"delta":round(net["delta"],4),"gamma":round(net["gamma"],6),
            "vega":round(net["vega"],4),"theta":round(net["theta"],4),
            "net_iv":round(sum(net["ivs"])/len(net["ivs"]),2) if net["ivs"] else 0.0}


# ── IV series ──────────────────────────────────────────────────────────────────

def get_iv_series_live(index, strike, expiry_label, cp,
                        tf_minutes=5, date_str=None) -> pd.DataFrame:
    _validate_leg(index, strike, expiry_label, cp)
    df   = _get_candles(index, strike, expiry_label, cp, tf_minutes, date_str)
    spot = get_spot_price(index)
    T    = _days_to_expiry(expiry_label, index)
    rows = []
    for ts, row in df.iterrows():
        try:
            iv_pct = round(
                implied_volatility(row["close"],spot,strike,T,RISK_FREE_RATE,cp)*100, 2)
        except Exception:
            iv_pct = 0.0
        rows.append({"time": ts, "iv_pct": iv_pct})
    return pd.DataFrame(rows)


# ── multiplier series ──────────────────────────────────────────────────────────

def get_multiplier_series_live(sx_strike, sx_expiry, n_strike, n_expiry,
                                interval=1, date_str=None) -> pd.DataFrame:
    for idx, st_val, exp, cp in [
        ("SENSEX", sx_strike, sx_expiry, "CE"),
        ("SENSEX", sx_strike, sx_expiry, "PE"),
        ("NIFTY",  n_strike,  n_expiry,  "CE"),
        ("NIFTY",  n_strike,  n_expiry,  "PE"),
    ]:
        _validate_leg(idx, st_val, exp, cp)

    sx_ce = _get_candles("SENSEX",sx_strike,sx_expiry,"CE",interval,date_str)["close"]
    sx_pe = _get_candles("SENSEX",sx_strike,sx_expiry,"PE",interval,date_str)["close"]
    n_ce  = _get_candles("NIFTY", n_strike, n_expiry, "CE",interval,date_str)["close"]
    n_pe  = _get_candles("NIFTY", n_strike, n_expiry, "PE",interval,date_str)["close"]

    sx_synth   = sx_strike + sx_ce - sx_pe
    n_synth    = n_strike  + n_ce  - n_pe
    multiplier = (sx_synth / n_synth).round(4)

    return pd.DataFrame({
        "time":       sx_synth.index,
        "multiplier": multiplier.values,
        "sx_synth":   sx_synth.values.round(2),
        "n_synth":    n_synth.values.round(2),
    }).reset_index(drop=True)
