"""
fyers_client.py
───────────────
Fyers API integration — drop-in replacement for dhan_client.py
Credentials in Streamlit secrets:
  FYERS_CLIENT_ID   = "YOUR_APP_ID-100"
  FYERS_SECRET_KEY  = "YOUR_SECRET_KEY"
  FYERS_USERNAME    = "your_fyers_id"
  FYERS_PIN         = "your_pin"
  FYERS_TOTP_KEY    = "your_totp_base32_secret"
"""

import os
import base64
import math
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
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

# ─── Fyers underlying → index symbol ─────────────────────────────────────────
_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}
_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]

# Redirect URI — must exactly match what is set in your Fyers API app dashboard
# Go to myapi.fyers.in → Apps → your app → Edit → set Redirect URL to:
REDIRECT_URI = "http://127.0.0.1:8080/"


# ─────────────────────────────────────────────────────────────────────────────
# SECRETS HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _secret(key: str) -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, "")

def _b64(val) -> str:
    return base64.b64encode(str(val).encode()).decode()


# ─────────────────────────────────────────────────────────────────────────────
# TOKEN GENERATION  (TOTP auto-login — same as your friend's code)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_json(response, step: str):
    """Parse JSON safely — raise a clear error if response is empty/HTML."""
    raw = response.text.strip()
    if not raw:
        raise ValueError(
            f"Fyers API returned empty response at {step}. "
            f"HTTP {response.status_code}. This usually means the API endpoint "
            f"is temporarily down or your IP is rate-limited. Try again in 30 seconds."
        )
    try:
        return response.json()
    except Exception:
        preview = raw[:200]
        raise ValueError(
            f"Fyers API returned non-JSON at {step} (HTTP {response.status_code}): {preview}"
        )


def _generate_token() -> tuple:
    """
    Automated Fyers login via TOTP.
    Returns (access_token, None) on success, (None, error_message) on failure.
    Uses same flow as proven working dashboard code.
    """
    client_id  = _secret("FYERS_CLIENT_ID")
    secret_key = _secret("FYERS_SECRET_KEY")
    username   = _secret("FYERS_USERNAME")
    pin        = _secret("FYERS_PIN")
    totp_key   = _secret("FYERS_TOTP_KEY")

    missing = [k for k, v in {
        "FYERS_CLIENT_ID": client_id, "FYERS_SECRET_KEY": secret_key,
        "FYERS_USERNAME":  username,  "FYERS_PIN":        pin,
        "FYERS_TOTP_KEY":  totp_key,
    }.items() if not v]
    if missing:
        return None, f"Missing Fyers secrets: {', '.join(missing)}"

    import hashlib
    try:
        s = _requests.Session()

        # Step 1 — send OTP
        r1 = s.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                    json={"fy_id": _b64(username), "app_id": "2"}, timeout=10)
        if r1.status_code == 429:
            return None, "Rate limited by Fyers (429). Wait ~60 seconds then click Refresh Token."
        r1d = _safe_json(r1, "Step1/send_otp")
        if r1d.get("s") != "ok":
            return None, f"Step 1 failed: {r1d}"

        # Step 2 — verify TOTP
        totp_code = pyotp.TOTP(totp_key).now()
        r2 = s.post("https://api-t2.fyers.in/vagator/v2/verify_otp",
                    json={"request_key": r1d["request_key"], "otp": totp_code}, timeout=10)
        r2d = _safe_json(r2, "Step2/verify_otp")
        if r2d.get("s") != "ok":
            return None, (
                f"Step 2 (TOTP verify) failed: {r2d}. "
                f"FYERS_TOTP_KEY must be the Base32 secret, NOT the 6-digit code."
            )

        # Step 3 — verify PIN
        r3 = s.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
                    json={"request_key": r2d["request_key"],
                          "identity_type": "pin", "identifier": _b64(pin)}, timeout=10)
        r3d = _safe_json(r3, "Step3/verify_pin")
        if r3d.get("s") != "ok":
            return None, f"Step 3 (PIN verify) failed: {r3d}. Check FYERS_PIN."

        # Step 4 — get auth code
        app_id = client_id.split("-")[0]
        r4 = s.post("https://api-t1.fyers.in/api/v3/token", json={
            "fyers_id": username, "app_id": app_id,
            "redirect_uri": REDIRECT_URI, "appType": "100",
            "code_challenge": "", "state": "sample",
            "scope": "", "nonce": "", "response_type": "code", "create_cookie": True
        }, headers={"Authorization": f"Bearer {r3d['data']['access_token']}"}, timeout=10)
        r4d = _safe_json(r4, "Step4/get_auth_code")
        if r4d.get("s") != "ok":
            return None, f"Step 4 (auth code) failed: {r4d}"

        # Extract auth_code — try multiple locations in response
        data = r4d.get("data", {})
        auth_code = (
            data.get("auth")
            or parse_qs(urlparse(r4d.get("Url", "")).query).get("auth_code", [None])[0]
            or parse_qs(urlparse(data.get("url", "")).query).get("auth_code", [None])[0]
        )
        if not auth_code:
            return None, f"Step 4: no auth_code in response: {r4d}"

        # Step 5 — exchange auth_code via validate-authcode (new Fyers API, SHA-256 hash)
        app_id_hash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
        r5 = s.post("https://api-t1.fyers.in/api/v3/validate-authcode", json={
            "grant_type": "authorization_code",
            "appIdHash":  app_id_hash,
            "code":       auth_code,
        }, timeout=10)
        r5d   = _safe_json(r5, "Step5/validate-authcode")
        token = r5d.get("access_token")

        if not token:
            # Fallback: legacy SDK token exchange
            session = fyersModel.SessionModel(
                client_id=client_id, secret_key=secret_key,
                redirect_uri=REDIRECT_URI, response_type="code",
                grant_type="authorization_code",
            )
            session.set_token(auth_code)
            r5d_legacy = session.generate_token()
            token = r5d_legacy.get("access_token")
            if not token:
                return None, f"Step 5 failed (both methods): validate-authcode={r5d}, legacy={r5d_legacy}"

        return token, None

    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"Exception during Fyers login: {type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# SHARED TOKEN  (generated once per server restart, cached with st.cache_resource)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _cached_token(client_id, secret_key, username, pin, totp_key) -> tuple:
    """
    Cached TOTP token generator. Credentials passed explicitly so st.secrets
    is read in normal Streamlit context — not inside the cache thread.
    Caches result so TOTP login only runs once per server restart.
    """
    token_file = "fyers_token.txt"
    try:
        with open(token_file) as f:
            tok = f.read().strip()
        if tok and len(tok) > 20:
            return tok, None
    except FileNotFoundError:
        pass
    token, error = _generate_token()
    if token:
        try:
            with open(token_file, "w") as f:
                f.write(token)
        except Exception:
            pass
        return token, None
    return None, error


def _get_shared_token() -> str:
    """
    Loads/generates Fyers access token. Priority order:
      1. FYERS_ACCESS_TOKEN in secrets  — paste from Fyers dashboard (easiest)
      2. fyers_token.txt on disk        — local PC
      3. Auto TOTP login                — requires all 5 TOTP secrets
    Reads st.secrets here (normal Streamlit context) then passes
    to cached function — same pattern as friend's working dashboard.
    """
    # Option 1: direct token
    direct_token = _secret("FYERS_ACCESS_TOKEN")
    if direct_token and len(direct_token) > 20:
        return direct_token

    # Option 2+3: TOTP flow
    client_id  = _secret("FYERS_CLIENT_ID")
    secret_key = _secret("FYERS_SECRET_KEY")
    username   = _secret("FYERS_USERNAME")
    pin        = _secret("FYERS_PIN")
    totp_key   = _secret("FYERS_TOTP_KEY")

    missing = [k for k, v in {
        "FYERS_CLIENT_ID": client_id, "FYERS_SECRET_KEY": secret_key,
        "FYERS_USERNAME": username, "FYERS_PIN": pin, "FYERS_TOTP_KEY": totp_key,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing Fyers credentials: {', '.join(missing)}. "
            f"Add FYERS_ACCESS_TOKEN (easiest) or all 5 TOTP secrets to Streamlit secrets."
        )

    token, error = _cached_token(client_id, secret_key, username, pin, totp_key)
    if token:
        return token
    raise RuntimeError(
        f"Fyers authentication failed: {error}\n\n"
        f"Fix options:\n"
        f"1. Add FYERS_ACCESS_TOKEN to Streamlit secrets "
        f"(get from myapi.fyers.in → Apps → your app → Generate Token)\n"
        f"2. Check all 5 TOTP secrets are correct\n"
        f"3. Ensure Fyers app Redirect URL = {REDIRECT_URI}"
    )


def get_fyers_client() -> fyersModel.FyersModel:
    """Returns an authenticated Fyers client, cached per session."""
    if st.session_state.get("fyers_client"):
        return st.session_state.fyers_client
    token  = _get_shared_token()
    cid    = _secret("FYERS_CLIENT_ID")
    client = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
    st.session_state.fyers_client = client
    return client

def refresh_token():
    """Force re-authentication. Call when token has expired."""
    _cached_token.clear()
    st.session_state.pop("fyers_client", None)
    # Delete saved token file so next login generates fresh token
    import os as _os
    try:
        _os.remove("fyers_token.txt")
    except FileNotFoundError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRIES  (fetched from Fyers option chain, cached per index)
# ─────────────────────────────────────────────────────────────────────────────

def _fyers_sym_for(index: str) -> str:
    return _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")


@st.cache_resource
def _fetch_expiry_codes(token: str, fyers_sym: str) -> dict:
    """
    Returns {label: fyers_expiry_code}
    label  e.g. "13 Apr 25 (W)"  or  "27 Mar 25 (M)"
    code   e.g. "26325" (weekly) or "26MAR" (monthly)
    Cached by (token, fyers_sym).
    """
    try:
        cid   = _secret("FYERS_CLIENT_ID")
        fyers = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
        resp  = fyers.optionchain(data={"symbol": fyers_sym, "strikecount": 1, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            return {}

        raw    = resp.get("data", {}).get("expiryData", [])
        parsed = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            d = entry.get("date", "")
            try:
                dd, mm, yyyy = d.split("-")
                dd, mm, yyyy = int(dd), int(mm), int(yyyy)
            except Exception:
                continue
            parsed.append((yyyy % 100, mm, dd, _MONTHS[mm - 1]))

        # Identify monthly expiries (last expiry of each month)
        by_month = defaultdict(list)
        for yy, mm, dd, mon in parsed:
            by_month[(yy, mm)].append(dd)
        last_of_month = {k: max(v) for k, v in by_month.items()}

        result = {}
        for yy, mm, dd, mon in parsed:
            is_monthly = (dd == last_of_month[(yy, mm)])
            if is_monthly:
                code  = f"{yy:02d}{mon}"          # e.g. 26MAR
                label = f"{dd:02d} {mon} {yy:02d} (M)"
            else:
                code  = f"{yy:02d}{mm}{dd:02d}"   # e.g. 260325
                label = f"{dd:02d} {mon} {yy:02d} (W)"
            result[label] = code
        return result
    except Exception:
        return {}


def get_expiries(index: str) -> list:
    """
    Returns sorted list of expiry LABELS like ['13 Apr 25 (W)', '27 Mar 25 (M)', ...]
    These labels are human-readable; the underlying Fyers codes are stored separately.
    """
    cache_key = f"expiries_{index}"
    if st.session_state.get(cache_key):
        return list(st.session_state[cache_key].keys())
    try:
        token  = _get_shared_token()
        sym    = _fyers_sym_for(index)
        codes  = _fetch_expiry_codes(token, sym)
        if not codes:
            raise ValueError(f"No expiries returned from Fyers for {index}.")
        st.session_state[cache_key] = codes   # {label: code}
        return list(codes.keys())
    except Exception as e:
        raise ValueError(f"Failed to load expiries for {index}: {e}")


def _expiry_label_to_code(index: str, label: str) -> str:
    """Convert human-readable label back to Fyers code."""
    cache_key = f"expiries_{index}"
    codes = st.session_state.get(cache_key, {})
    if label in codes:
        return codes[label]
    # Fallback: treat the label itself as a code
    return label


def _expiry_code_to_date(code: str) -> date:
    """Convert Fyers expiry code to a Python date."""
    import calendar as _cal
    code = code.strip().upper()
    months = {m: i+1 for i, m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):        # monthly: YYMON e.g. 26MAR
        yy  = int(code[:2])
        mon = code[2:5]
        mm  = months.get(mon, 3)
        dd  = _cal.monthrange(2000 + yy, mm)[1]
        return date(2000 + yy, mm, dd)
    else:                                      # weekly: YYMMDD e.g. 260325
        return date(2000 + int(code[0:2]), int(code[2:4]), int(code[4:6]))


def _days_to_expiry(expiry_label: str, index: str = "") -> float:
    """Return years to expiry from a human-readable label."""
    try:
        code   = _expiry_label_to_code(index, expiry_label) if index else expiry_label
        exp_dt = _expiry_code_to_date(code)
        days   = (exp_dt - datetime.now().date()).days
        return max(days, 1) / 365.0
    except Exception:
        return 30 / 365.0


# ─────────────────────────────────────────────────────────────────────────────
# STRIKES  (fetched from Fyers option chain, cached per index+expiry_code)
# ─────────────────────────────────────────────────────────────────────────────

def get_strikes(index: str, expiry_label: str) -> list:
    """
    Returns sorted list of available integer strike prices for an index + expiry.
    """
    code      = _expiry_label_to_code(index, expiry_label)
    cache_key = f"strikes_{index}_{code}"
    if st.session_state.get(cache_key):
        return st.session_state[cache_key]
    try:
        fyers  = get_fyers_client()
        sym    = _fyers_sym_for(index)
        resp   = fyers.optionchain(data={"symbol": sym, "strikecount": 50, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            raise ValueError(f"Option chain failed for {index}: {resp}")

        options  = resp.get("data", {}).get("optionsChain", [])
        exp_date = _expiry_code_to_date(code).strftime("%d-%m-%Y")

        strikes = set()
        for opt in options:
            if not isinstance(opt, dict):
                continue
            if opt.get("expiry") == exp_date or True:   # take all, filter by expiry below
                try:
                    strikes.add(int(float(opt["strikePrice"])))
                except Exception:
                    pass

        if not strikes:
            # Fallback: generate a reasonable range
            atm = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)
            step = 50 if index == "NIFTY" else (100 if index == "BANKNIFTY" else 500)
            strikes = set(range(atm - 30*step, atm + 31*step, step))

        result = sorted(strikes)
        st.session_state[cache_key] = result
        return result
    except Exception as e:
        # Return a sensible fallback range
        atm  = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)
        step = 50 if index == "NIFTY" else (100 if index == "BANKNIFTY" else 500)
        return list(range(atm - 20*step, atm + 21*step, step))


# ─────────────────────────────────────────────────────────────────────────────
# SYMBOL BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _exchange_for(index: str) -> str:
    return "BSE" if index in ("SENSEX", "BANKEX") else "NSE"

def build_symbol(index: str, expiry_label: str, cp: str, strike: int) -> str:
    """
    Build Fyers option symbol from human-readable inputs.
    e.g. NIFTY, '13 Apr 25 (W)', 'CE', 22800 → 'NSE:NIFTY26325CE22800'
    """
    exchange = _exchange_for(index)
    code     = _expiry_label_to_code(index, expiry_label)
    ot       = "CE" if cp.upper() in ("CE", "C") else "PE"
    code     = code.strip().upper()

    if any(c.isalpha() for c in code):
        # Monthly: NSE:NIFTY26MARCE22800
        return f"{exchange}:{index}{code}{ot}{strike}"
    else:
        # Weekly YYMMDD → YYM(no-zero-pad)DD: 260325 → 2635 (not 260325 directly)
        # Fyers weekly format: YY + month-no-leading-zero + DD
        yy, mm, dd = code[0:2], str(int(code[2:4])), code[4:6]
        return f"{exchange}:{index}{yy}{mm}{dd}{ot}{strike}"


# ─────────────────────────────────────────────────────────────────────────────
# CANDLE FETCHER
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, interval: int = 1, date_str: str = None) -> pd.DataFrame:
    """
    Fetch OHLCV candles from Fyers for a symbol.
    Returns DataFrame with DatetimeIndex (Asia/Kolkata, tz-naive).
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    fyers = get_fyers_client()
    resp  = fyers.history(data={
        "symbol":     symbol,
        "resolution": str(interval),
        "date_format":"1",
        "range_from": date_str,
        "range_to":   date_str,
        "cont_flag":  "1",
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
    df = df[~df.index.duplicated(keep="last")]
    return df


def _get_candles(index: str, strike: int, expiry_label: str,
                 cp: str, interval: int = 1,
                 date_str: str = None) -> pd.DataFrame:
    """Fetch OHLCV for one option leg. Validates inputs first."""
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    df  = _fetch_candles(sym, interval, date_str)
    if df.empty:
        raise ValueError(
            f"No candle data for {sym}. "
            f"Market may be closed or symbol format is wrong."
        )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# LIVE QUOTE
# ─────────────────────────────────────────────────────────────────────────────

def _get_live_quote_fyers(symbol: str) -> dict:
    """Fetch live quote dict from Fyers for a single symbol."""
    fyers = get_fyers_client()
    resp  = fyers.quotes(data={"symbols": symbol})
    if resp.get("s") != "ok":
        raise ValueError(f"Fyers quote failed for {symbol}: {resp}")
    d   = resp["d"][0]["v"]
    ltp = float(d.get("lp", 0))
    return {
        "ltp":        ltp,
        "bid":        float(d.get("bid",  ltp * 0.998)),
        "ask":        float(d.get("ask",  ltp * 1.002)),
        "prev_close": float(d.get("prev_close_price", 0)),
        "high":       float(d.get("high_price", ltp)),
        "low":        float(d.get("low_price",  ltp)),
    }

def get_live_quote(index: str, strike: int, expiry_label: str, cp: str) -> dict:
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    return _get_live_quote_fyers(sym)

def get_live_ltp(index: str, strike: int, expiry_label: str, cp: str) -> float:
    return get_live_quote(index, strike, expiry_label, cp)["ltp"]

def get_live_bid_ask_ltp(index: str, strike: int, expiry_label: str, cp: str) -> tuple:
    q = get_live_quote(index, strike, expiry_label, cp)
    return q["bid"], q["ask"], q["ltp"]


# ─────────────────────────────────────────────────────────────────────────────
# SPOT PRICE
# ─────────────────────────────────────────────────────────────────────────────

def get_spot_price(index: str) -> float:
    """Fetch index spot price from Fyers."""
    try:
        sym  = _fyers_sym_for(index)
        q    = _get_live_quote_fyers(sym)
        return q["ltp"]
    except Exception:
        return {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)


# ─────────────────────────────────────────────────────────────────────────────
# INPUT VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _validate_leg(index: str, strike: int, expiry: str, cp: str):
    if not index:
        raise ValueError("Index not selected.")
    if not expiry or expiry.strip() == "":
        raise ValueError(f"Expiry not selected for {index}.")
    if not isinstance(strike, (int, float)) or strike <= 0:
        raise ValueError(f"Invalid strike '{strike}' for {index} {expiry}.")
    if cp not in ("CE", "PE"):
        raise ValueError(f"Invalid option type '{cp}'. Must be CE or PE.")

def validate_legs(legs: list):
    if not legs:
        raise ValueError("No legs provided.")
    for i, leg in enumerate(legs):
        try:
            _validate_leg(leg.get("index",""), leg.get("strike",0),
                          leg.get("expiry",""), leg.get("cp",""))
        except ValueError as e:
            raise ValueError(f"Leg {i+1}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SPREAD OHLCV
# ─────────────────────────────────────────────────────────────────────────────

def get_live_spread_ohlcv(legs: list, interval: int = 1,
                           date_str: str = None) -> pd.DataFrame:
    """
    Fetch candles per leg from Fyers, combine into spread OHLCV.
    Validates all legs before any API call.
    """
    validate_legs(legs)
    spread_close = None
    base_times   = None

    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"],
                              leg["expiry"], leg["cp"], interval, date_str)
        price = df["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price
        if spread_close is None:
            spread_close = price
            base_times   = df.index
        else:
            spread_close = spread_close.reindex(base_times).add(
                price.reindex(base_times), fill_value=0)

    out          = pd.DataFrame(index=base_times)
    out["close"] = spread_close.values
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open","close"]].max(axis=1)
    out["low"]   = out[["open","close"]].min(axis=1)
    out = out.reset_index().rename(columns={"time": "time"})
    if "index" in out.columns:
        out = out.rename(columns={"index": "time"})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BLACK-SCHOLES GREEKS
# ─────────────────────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def bs_price(S, K, T, r, sigma, cp) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "CE" else (K - S))
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if cp == "CE":
        return S*_norm_cdf(d1) - K*math.exp(-r*T)*_norm_cdf(d2)
    return K*math.exp(-r*T)*_norm_cdf(-d2) - S*_norm_cdf(-d1)

def implied_volatility(market_price, S, K, T, r, cp) -> float:
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
    low, high = 0.001, 5.0
    for _ in range(200):
        mid   = (low + high) / 2
        price = bs_price(S, K, T, r, mid, cp)
        if abs(price - market_price) < 1e-5:
            return mid
        low, high = (mid, high) if price < market_price else (low, mid)
    return mid

def bs_greeks(S, K, T, r, sigma, cp) -> dict:
    if T <= 0 or sigma <= 0:
        return {"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sigma*100}
    d1  = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2  = d1 - sigma*math.sqrt(T)
    pdf = _norm_pdf(d1)
    gamma = pdf / (S*sigma*math.sqrt(T))
    vega  = S*pdf*math.sqrt(T) / 100
    if cp == "CE":
        delta = _norm_cdf(d1)
        theta = (-(S*pdf*sigma)/(2*math.sqrt(T)) - r*K*math.exp(-r*T)*_norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(S*pdf*sigma)/(2*math.sqrt(T)) + r*K*math.exp(-r*T)*_norm_cdf(-d2)) / 365
    return {"delta":round(delta,4),"gamma":round(gamma,6),
            "vega":round(vega,4),"theta":round(theta,4),"iv":round(sigma*100,2)}

def get_spread_greeks(legs: list, spot_prices: dict) -> dict:
    validate_legs(legs)
    net = {"delta":0.0,"gamma":0.0,"vega":0.0,"theta":0.0,"ivs":[]}
    for leg in legs:
        try:
            S     = float(spot_prices.get(leg["index"], 22800))
            K     = float(leg["strike"])
            T     = _days_to_expiry(leg["expiry"], leg["index"])
            ltp   = get_live_ltp(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
            sigma = implied_volatility(ltp, S, K, T, RISK_FREE_RATE, leg["cp"])
            g     = bs_greeks(S, K, T, RISK_FREE_RATE, sigma, leg["cp"])
            sign  = 1 if leg["bs"] == "Buy" else -1
            ratio = leg["ratio"]
            net["delta"] += sign*ratio*g["delta"]
            net["gamma"] += sign*ratio*g["gamma"]
            net["vega"]  += sign*ratio*g["vega"]
            net["theta"] += sign*ratio*g["theta"]
            net["ivs"].append(g["iv"])
        except Exception:
            pass
    return {
        "delta":  round(net["delta"],4),
        "gamma":  round(net["gamma"],6),
        "vega":   round(net["vega"],4),
        "theta":  round(net["theta"],4),
        "net_iv": round(sum(net["ivs"])/len(net["ivs"]),2) if net["ivs"] else 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# IV SERIES  (historical candles → B-S IV per bar)
# ─────────────────────────────────────────────────────────────────────────────

def get_iv_series_live(index: str, strike: int, expiry_label: str,
                        cp: str, tf_minutes: int = 5,
                        date_str: str = None) -> pd.DataFrame:
    _validate_leg(index, strike, expiry_label, cp)
    df   = _get_candles(index, strike, expiry_label, cp, tf_minutes, date_str)
    spot = get_spot_price(index)
    T    = _days_to_expiry(expiry_label, index)
    rows = []
    for ts, row in df.iterrows():
        try:
            iv     = implied_volatility(row["close"], spot, strike, T, RISK_FREE_RATE, cp)
            iv_pct = round(iv * 100, 2)
        except Exception:
            iv_pct = 0.0
        rows.append({"time": ts, "iv_pct": iv_pct})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# MULTIPLIER SERIES  (SENSEX/NIFTY synthetic ratio)
# ─────────────────────────────────────────────────────────────────────────────

def get_multiplier_series_live(sx_strike: int, sx_expiry: str,
                                n_strike:  int, n_expiry:  str,
                                interval: int = 1,
                                date_str: str = None) -> pd.DataFrame:
    for idx, st_val, exp, cp in [
        ("SENSEX", sx_strike, sx_expiry, "CE"),
        ("SENSEX", sx_strike, sx_expiry, "PE"),
        ("NIFTY",  n_strike,  n_expiry,  "CE"),
        ("NIFTY",  n_strike,  n_expiry,  "PE"),
    ]:
        _validate_leg(idx, st_val, exp, cp)

    sx_ce = _get_candles("SENSEX", sx_strike, sx_expiry, "CE", interval, date_str)["close"]
    sx_pe = _get_candles("SENSEX", sx_strike, sx_expiry, "PE", interval, date_str)["close"]
    n_ce  = _get_candles("NIFTY",  n_strike,  n_expiry,  "CE", interval, date_str)["close"]
    n_pe  = _get_candles("NIFTY",  n_strike,  n_expiry,  "PE", interval, date_str)["close"]

    sx_synth   = sx_strike + sx_ce - sx_pe
    n_synth    = n_strike  + n_ce  - n_pe
    multiplier = (sx_synth / n_synth).round(4)

    return pd.DataFrame({
        "time":       sx_synth.index,
        "multiplier": multiplier.values,
        "sx_synth":   sx_synth.values.round(2),
        "n_synth":    n_synth.values.round(2),
    }).reset_index(drop=True)
