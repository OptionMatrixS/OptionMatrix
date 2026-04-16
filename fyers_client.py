"""
fyers_client.py  —  Option Matrix
All Fyers API logic: auth, expiries, strikes, candles, quotes, Greeks.

Streamlit secrets required (add in Streamlit Cloud → Settings → Secrets):
  FYERS_CLIENT_ID  = "XXXX-100"          # your Fyers app client ID
  FYERS_SECRET_KEY = "your_secret"       # your Fyers app secret key
  FYERS_USERNAME   = "XY12345"           # your Fyers login ID (FY ID)
  FYERS_PIN        = "1234"              # your Fyers 4-digit PIN
  FYERS_TOTP_KEY   = "BASE32SECRET"      # Base32 TOTP secret (NOT the 6-digit code)

FYERS_CLIENT_ID format:
  ✓ Correct:   "ABCD1234-100"   →  app_id becomes "ABCD1234"
  ✗ Wrong:     "ABCD1234"       →  app_id becomes "ABCD1234" (still works)
  ✗ Wrong:     "100"            →  will fail

FYERS_TOTP_KEY:
  Go to Fyers → My Account → Security → TOTP → Setup
  Copy the TEXT SECRET (long Base32 string like JBSWY3DPEHPK3PXP)
  Do NOT paste the 6-digit code that changes every 30s

Redirect URL in Fyers API dashboard must be exactly: http://127.0.0.1:8080/
  Go to myapi.fyers.in → Apps → your app → Edit → set Redirect URL
"""

import os, base64, hashlib, math, importlib
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from collections import defaultdict
from urllib.parse import parse_qs, urlparse
import requests as _req

try:
    import pyotp
except ImportError:
    raise ImportError("pip install pyotp")

try:
    from fyers_apiv3 import fyersModel
except ImportError:
    raise ImportError("pip install fyers-apiv3")

RISK_FREE_RATE  = 0.065
REDIRECT_URI    = "http://127.0.0.1:8080/"
TOKEN_FILE      = "fyers_token.txt"

_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}
_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _s(key: str) -> str:
    """Read from Streamlit secrets, fall back to env var."""
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, "").strip()

def _b64(val: str) -> str:
    return base64.b64encode(str(val).encode()).decode()

def _safe_json(resp, step: str) -> dict:
    """Parse JSON; raise descriptive error if response is empty or HTML."""
    text = resp.text.strip() if resp.text else ""
    if not text:
        raise RuntimeError(
            f"Fyers returned EMPTY response at {step} (HTTP {resp.status_code}). "
            f"This means Fyers API is temporarily down or your IP is rate-limited. "
            f"Wait 60 seconds and click Refresh Token."
        )
    try:
        return resp.json()
    except Exception:
        raise RuntimeError(
            f"Fyers returned non-JSON at {step} (HTTP {resp.status_code}): {text[:300]}"
        )

# ─────────────────────────────────────────────────────────────────────────────
# TOTP LOGIN  —  exact same flow as friend's working dashboard
# ─────────────────────────────────────────────────────────────────────────────

def _generate_token(client_id: str, secret_key: str,
                    username: str, pin: str, totp_key: str) -> tuple:
    """
    5-step Fyers TOTP login.
    Credentials passed as arguments (NOT read from st.secrets here)
    so this function is safe to call from inside @st.cache_resource.
    Returns (access_token, None) on success, (None, error_str) on failure.
    """
    # The numeric suffix after "-" is the app type.
    # app_id for API calls = everything before the last "-100" suffix
    # e.g. "ABCD1234-100" → app_id = "ABCD1234"
    app_id = client_id.split("-")[0]

    try:
        sess = _req.Session()
        # No special headers needed — friend's code doesn't set them either

        # ── Step 1: send login OTP ────────────────────────────────────────────
        r1 = sess.post(
            "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
            json={"fy_id": _b64(username), "app_id": "2"},
            timeout=15)
        if r1.status_code == 429:
            return None, ("Rate limited by Fyers (HTTP 429). "
                          "Wait 60 seconds then click Refresh Token.")
        d1 = _safe_json(r1, "Step1/send_otp")
        if d1.get("s") != "ok":
            return None, f"Step 1 (send OTP) failed: {d1}"

        # ── Step 2: verify TOTP ───────────────────────────────────────────────
        totp_code = pyotp.TOTP(totp_key).now()
        r2 = sess.post(
            "https://api-t2.fyers.in/vagator/v2/verify_otp",
            json={"request_key": d1["request_key"], "otp": totp_code},
            timeout=15)
        d2 = _safe_json(r2, "Step2/verify_otp")
        if d2.get("s") != "ok":
            return None, (
                f"Step 2 (verify TOTP) failed: {d2}. "
                f"FYERS_TOTP_KEY must be the Base32 SECRET shown during TOTP setup, "
                f"not the 6-digit code. It looks like: JBSWY3DPEHPK3PXP"
            )

        # ── Step 3: verify PIN ────────────────────────────────────────────────
        r3 = sess.post(
            "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
            json={
                "request_key":   d2["request_key"],
                "identity_type": "pin",
                "identifier":    _b64(pin),
            },
            timeout=15)
        d3 = _safe_json(r3, "Step3/verify_pin")
        if d3.get("s") != "ok":
            return None, (
                f"Step 3 (verify PIN) failed: {d3}. "
                f"Check FYERS_PIN — it is your 4-digit Fyers login PIN."
            )

        # ── Step 4: get auth code ─────────────────────────────────────────────
        # IMPORTANT: appType must be "100" (personal app). This must match
        # the Redirect URL set in your Fyers API dashboard.
        r4 = sess.post(
            "https://api-t1.fyers.in/api/v3/token",
            json={
                "fyers_id":      username,
                "app_id":        app_id,       # "ABCD1234" not "ABCD1234-100"
                "redirect_uri":  REDIRECT_URI,
                "appType":       "100",
                "code_challenge":"",
                "state":         "sample",
                "scope":         "",
                "nonce":         "",
                "response_type": "code",
                "create_cookie": True,
            },
            headers={"Authorization": f"Bearer {d3['data']['access_token']}"},
            timeout=15)
        d4 = _safe_json(r4, "Step4/get_auth_code")
        if d4.get("s") != "ok":
            return None, (
                f"Step 4 (auth code) failed: {d4}. "
                f"Most common causes:\n"
                f"• 'redirectUrl mismatch' → Redirect URL in Fyers API dashboard must be "
                f"exactly: {REDIRECT_URI}\n"
                f"• 'apptype mismatch' → FYERS_CLIENT_ID must include '-100' suffix "
                f"e.g. 'ABCD1234-100'\n"
                f"• 'Invalid app' → Check FYERS_CLIENT_ID and FYERS_SECRET_KEY are correct"
            )

        # Extract auth_code — Fyers puts it in different places depending on version
        data     = d4.get("data", {})
        auth_url = d4.get("Url", "") or data.get("url", "")
        auth_code = (
            data.get("auth_code")
            or data.get("auth")
            or parse_qs(urlparse(auth_url).query).get("auth_code", [None])[0]
        )
        if not auth_code:
            return None, (
                f"Step 4: could not extract auth_code from response: {d4}"
            )

        # ── Step 5: exchange auth_code for access token ───────────────────────
        # New Fyers API v3: use SHA-256 hash of "app_id:secret_key"
        app_id_hash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
        r5 = sess.post(
            "https://api-t1.fyers.in/api/v3/validate-authcode",
            json={
                "grant_type": "authorization_code",
                "appIdHash":  app_id_hash,
                "code":       auth_code,
            },
            timeout=15)
        d5    = _safe_json(r5, "Step5/validate-authcode")
        token = d5.get("access_token")

        if not token:
            # Fallback: legacy SessionModel (older Fyers API)
            try:
                session = fyersModel.SessionModel(
                    client_id=client_id, secret_key=secret_key,
                    redirect_uri=REDIRECT_URI, response_type="code",
                    grant_type="authorization_code",
                )
                session.set_token(auth_code)
                d5b   = session.generate_token()
                token = d5b.get("access_token")
                if not token:
                    return None, (
                        f"Step 5 failed (both methods).\n"
                        f"validate-authcode response: {d5}\n"
                        f"legacy SDK response: {d5b}"
                    )
            except Exception as e:
                return None, (
                    f"Step 5 failed: validate-authcode={d5}, "
                    f"legacy SDK exception={e}"
                )

        return token, None

    except RuntimeError as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# CACHED TOKEN  (credentials passed as args — safe inside @st.cache_resource)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _cached_token(client_id: str, secret_key: str,
                  username: str, pin: str, totp_key: str) -> tuple:
    """
    Calls _generate_token once per server restart and caches the result.
    Credentials passed as args (not read from st.secrets) so this works
    correctly on Streamlit Cloud where st.secrets is unavailable inside cache.
    Returns (token, None) or (None, error_str).
    """
    # Try saved token file first (survives hot-reloads)
    try:
        with open(TOKEN_FILE) as f:
            tok = f.read().strip()
        if tok and len(tok) > 20:
            return tok, None
    except FileNotFoundError:
        pass

    # Generate fresh token via TOTP
    token, error = _generate_token(client_id, secret_key, username, pin, totp_key)
    if token:
        try:
            with open(TOKEN_FILE, "w") as f:
                f.write(token)
        except Exception:
            pass
        return token, None
    return None, error


def get_token() -> str:
    """
    Entry point for getting a valid Fyers token.
    Reads st.secrets HERE (in normal Streamlit context),
    then delegates to the cached function.
    Raises RuntimeError with a clear message on failure.
    """
    client_id  = _s("FYERS_CLIENT_ID")
    secret_key = _s("FYERS_SECRET_KEY")
    username   = _s("FYERS_USERNAME")
    pin        = _s("FYERS_PIN")
    totp_key   = _s("FYERS_TOTP_KEY")

    missing = [k for k, v in {
        "FYERS_CLIENT_ID":  client_id,
        "FYERS_SECRET_KEY": secret_key,
        "FYERS_USERNAME":   username,
        "FYERS_PIN":        pin,
        "FYERS_TOTP_KEY":   totp_key,
    }.items() if not v]

    if missing:
        raise RuntimeError(
            f"Missing Fyers secrets: {', '.join(missing)}\n\n"
            f"On Streamlit Cloud: go to your app → ⋮ → Settings → Secrets and add:\n"
            f'  FYERS_CLIENT_ID  = "XXXX-100"\n'
            f'  FYERS_SECRET_KEY = "your_secret"\n'
            f'  FYERS_USERNAME   = "XY12345"\n'
            f'  FYERS_PIN        = "1234"\n'
            f'  FYERS_TOTP_KEY   = "BASE32SECRET"'
        )

    token, error = _cached_token(client_id, secret_key, username, pin, totp_key)
    if token:
        return token

    raise RuntimeError(
        f"Fyers login failed: {error}\n\n"
        f"Set FYERS_ACCESS_TOKEN in secrets OR fix TOTP secrets. "
        f"Redirect URL in Fyers dashboard must be: {REDIRECT_URI}"
    )


def get_fyers_client() -> fyersModel.FyersModel:
    """Returns an authenticated Fyers client, cached per session."""
    if st.session_state.get("_fyers_client"):
        return st.session_state._fyers_client
    token  = get_token()
    cid    = _s("FYERS_CLIENT_ID")
    client = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
    st.session_state._fyers_client = client
    return client


def refresh_token():
    """Clear cached token and force re-authentication on next API call."""
    _cached_token.clear()
    st.session_state.pop("_fyers_client", None)
    # Delete token file so fresh login happens
    try:
        os.remove(TOKEN_FILE)
    except FileNotFoundError:
        pass
    # Clear cached expiries and strikes
    for key in list(st.session_state.keys()):
        if key.startswith("expiries_") or key.startswith("strikes_"):
            del st.session_state[key]


# ─────────────────────────────────────────────────────────────────────────────
# EXPIRIES
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _fetch_expiry_codes(token: str, cid: str, fyers_sym: str) -> dict:
    """
    Returns {label: code} for all future expiries of an index.
    label = "13 Apr 25 (W)"  code = "26413"  (weekly)
    label = "29 May 25 (M)"  code = "26MAY"  (monthly)
    Cached by (token, cid, fyers_sym) — refreshed when token changes.
    """
    try:
        fyers = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
        resp  = fyers.optionchain(
            data={"symbol": fyers_sym, "strikecount": 1, "timestamp": ""})
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

        # Last expiry of each calendar month = monthly
        by_month = defaultdict(list)
        for yy, mm, dd, mon in parsed:
            by_month[(yy, mm)].append(dd)
        last_of_month = {k: max(v) for k, v in by_month.items()}

        result = {}
        for yy, mm, dd, mon in parsed:
            is_monthly = (dd == last_of_month[(yy, mm)])
            if is_monthly:
                code  = f"{yy:02d}{mon}"           # e.g. "26MAY"
                label = f"{dd:02d} {mon} {yy:02d} (M)"
            else:
                code  = f"{yy:02d}{mm:02d}{dd:02d}" # e.g. "260416"
                label = f"{dd:02d} {mon} {yy:02d} (W)"
            result[label] = code
        return result
    except Exception:
        return {}


def get_expiries(index: str) -> list:
    """Returns list of expiry labels for an index. Raises on failure."""
    cache_key = f"expiries_{index}"
    if st.session_state.get(cache_key):
        return list(st.session_state[cache_key].keys())
    try:
        token = get_token()
        cid   = _s("FYERS_CLIENT_ID")
        sym   = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
        codes = _fetch_expiry_codes(token, cid, sym)
        if not codes:
            raise ValueError(f"Fyers returned no expiries for {index}.")
        st.session_state[cache_key] = codes
        return list(codes.keys())
    except Exception as e:
        raise ValueError(f"Failed to load expiries for {index}: {e}")


def _label_to_code(index: str, label: str) -> str:
    cache_key = f"expiries_{index}"
    codes = st.session_state.get(cache_key, {})
    return codes.get(label, label)   # fall back to label itself


def _code_to_date(code: str) -> date:
    import calendar as _cal
    code = code.strip().upper()
    months = {m: i+1 for i, m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):        # monthly e.g. "26MAY"
        yy = int(code[:2])
        mon = code[2:5]
        mm = months.get(mon, 3)
        dd = _cal.monthrange(2000+yy, mm)[1]
        return date(2000+yy, mm, dd)
    else:                                      # weekly e.g. "260416"
        return date(2000+int(code[0:2]), int(code[2:4]), int(code[4:6]))


def _days_to_expiry(expiry_label: str, index: str = "") -> float:
    try:
        code   = _label_to_code(index, expiry_label) if index else expiry_label
        exp_dt = _code_to_date(code)
        days   = (exp_dt - datetime.now().date()).days
        return max(days, 1) / 365.0
    except Exception:
        return 30 / 365.0


# ─────────────────────────────────────────────────────────────────────────────
# STRIKES
# ─────────────────────────────────────────────────────────────────────────────

def get_strikes(index: str, expiry_label: str) -> list:
    """Returns sorted list of integer strike prices. Falls back to ATM range."""
    code      = _label_to_code(index, expiry_label)
    cache_key = f"strikes_{index}_{code}"
    if st.session_state.get(cache_key):
        return st.session_state[cache_key]
    try:
        fyers = get_fyers_client()
        sym   = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
        resp  = fyers.optionchain(
            data={"symbol": sym, "strikecount": 50, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            raise ValueError(f"optionchain failed: {resp}")

        options = resp.get("data", {}).get("optionsChain", [])
        strikes = set()
        for opt in options:
            if isinstance(opt, dict):
                try:
                    strikes.add(int(float(opt["strikePrice"])))
                except Exception:
                    pass

        if strikes:
            result = sorted(strikes)
            st.session_state[cache_key] = result
            return result
    except Exception:
        pass

    # Fallback: generate ATM range
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
    Build Fyers option symbol.
    NIFTY, '16 Apr 25 (W)', 'CE', 22800  →  'NSE:NIFTY26416CE22800'
    SENSEX, '29 May 25 (M)', 'CE', 82000  →  'BSE:SENSEX26MAYCE82000'
    """
    exchange = _exchange_for(index)
    code     = _label_to_code(index, expiry_label)
    ot       = "CE" if cp.upper() in ("CE", "C") else "PE"
    code     = code.strip().upper()

    if any(c.isalpha() for c in code):
        # Monthly: BSE:SENSEX26MAYCE82000
        return f"{exchange}:{index}{code}{ot}{strike}"
    else:
        # Weekly YYMMDD → YYM(no-leading-zero)DD
        # "260416" → yy=26, mm=4, dd=16 → "NSE:NIFTY26416CE22800"
        yy = code[0:2]
        mm = str(int(code[2:4]))   # removes leading zero: "04" → "4"
        dd = code[4:6]
        return f"{exchange}:{index}{yy}{mm}{dd}{ot}{strike}"


# ─────────────────────────────────────────────────────────────────────────────
# CANDLES
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, interval: int = 1,
                   date_str: str = None) -> pd.DataFrame:
    """Fetch OHLCV from Fyers. Returns DataFrame indexed by IST datetime."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    fyers = get_fyers_client()
    resp  = fyers.history(data={
        "symbol":      symbol,
        "resolution":  str(interval),
        "date_format": "1",
        "range_from":  date_str,
        "range_to":    date_str,
        "cont_flag":   "1",
    })
    if resp.get("s") != "ok" or not resp.get("candles"):
        return pd.DataFrame()
    df = pd.DataFrame(resp["candles"],
                      columns=["ts","open","high","low","close","volume"])
    df["time"] = (pd.to_datetime(df["ts"], unit="s")
                  .dt.tz_localize("UTC")
                  .dt.tz_convert("Asia/Kolkata")
                  .dt.tz_localize(None))
    return df.drop(columns=["ts"]).set_index("time")


def _get_candles(index: str, strike: int, expiry_label: str,
                 cp: str, interval: int = 1, date_str: str = None) -> pd.DataFrame:
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    df  = _fetch_candles(sym, interval, date_str)
    if df.empty:
        raise ValueError(
            f"No candle data returned for {sym}. "
            f"Check date is a trading day and contract existed then.")
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
    return {
        "ltp":        ltp,
        "bid":        float(v.get("bid",             ltp * 0.998)),
        "ask":        float(v.get("ask",             ltp * 1.002)),
        "prev_close": float(v.get("prev_close_price", 0)),
        "high":       float(v.get("high_price",      ltp)),
        "low":        float(v.get("low_price",       ltp)),
    }


def get_live_quote(index: str, strike: int, expiry_label: str, cp: str) -> dict:
    _validate_leg(index, strike, expiry_label, cp)
    return _quote(build_symbol(index, expiry_label, cp, strike))

def get_live_ltp(index: str, strike: int, expiry_label: str, cp: str) -> float:
    return get_live_quote(index, strike, expiry_label, cp)["ltp"]

def get_live_bid_ask_ltp(index: str, strike: int,
                          expiry_label: str, cp: str) -> tuple:
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
    if not index:
        raise ValueError("Index not selected.")
    if not expiry or not expiry.strip():
        raise ValueError(f"Expiry not selected for {index}.")
    if not isinstance(strike, (int, float)) or strike <= 0:
        raise ValueError(f"Invalid strike '{strike}'.")
    if cp not in ("CE", "PE"):
        raise ValueError(f"Option type must be CE or PE, got '{cp}'.")

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
    validate_legs(legs)
    spread = None
    base   = None
    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"],
                              leg["expiry"], leg["cp"], interval, date_str)
        price = df["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price
        if spread is None:
            spread = price
            base   = df.index
        else:
            spread = spread.reindex(base).add(price.reindex(base), fill_value=0)

    out          = pd.DataFrame(index=base)
    out["close"] = spread.values
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open","close"]].max(axis=1)
    out["low"]   = out[["open","close"]].min(axis=1)
    out = out.reset_index()
    if "time" not in out.columns and "index" in out.columns:
        out = out.rename(columns={"index": "time"})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BLACK-SCHOLES GREEKS
# ─────────────────────────────────────────────────────────────────────────────

def _ncdf(x):
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0

def _npdf(x):
    return math.exp(-0.5*x*x) / math.sqrt(2*math.pi)

def bs_price(S, K, T, r, sigma, cp):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S-K) if cp=="CE" else (K-S))
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if cp == "CE":
        return S*_ncdf(d1) - K*math.exp(-r*T)*_ncdf(d2)
    return K*math.exp(-r*T)*_ncdf(-d2) - S*_ncdf(-d1)

def implied_volatility(mkt_price, S, K, T, r, cp):
    if mkt_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
    lo, hi = 0.001, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        p   = bs_price(S, K, T, r, mid, cp)
        if abs(p - mkt_price) < 1e-5:
            return mid
        lo, hi = (mid, hi) if p < mkt_price else (lo, mid)
    return mid

def bs_greeks(S, K, T, r, sigma, cp):
    if T <= 0 or sigma <= 0:
        return {"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sigma*100}
    d1  = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2  = d1 - sigma*math.sqrt(T)
    pdf = _npdf(d1)
    g   = pdf / (S*sigma*math.sqrt(T))
    v   = S*pdf*math.sqrt(T) / 100
    if cp == "CE":
        d = _ncdf(d1)
        t = (-(S*pdf*sigma)/(2*math.sqrt(T)) - r*K*math.exp(-r*T)*_ncdf(d2)) / 365
    else:
        d = _ncdf(d1) - 1
        t = (-(S*pdf*sigma)/(2*math.sqrt(T)) + r*K*math.exp(-r*T)*_ncdf(-d2)) / 365
    return {"delta":round(d,4),"gamma":round(g,6),
            "vega":round(v,4),"theta":round(t,4),"iv":round(sigma*100,2)}

def get_spread_greeks(legs, spot_prices):
    validate_legs(legs)
    net = {"delta":0.0,"gamma":0.0,"vega":0.0,"theta":0.0,"ivs":[]}
    for leg in legs:
        try:
            S     = float(spot_prices.get(leg["index"], 22800))
            K     = float(leg["strike"])
            T     = _days_to_expiry(leg["expiry"], leg["index"])
            ltp   = get_live_ltp(leg["index"], leg["strike"],
                                  leg["expiry"], leg["cp"])
            sigma = implied_volatility(ltp, S, K, T, RISK_FREE_RATE, leg["cp"])
            g     = bs_greeks(S, K, T, RISK_FREE_RATE, sigma, leg["cp"])
            sign  = 1 if leg["bs"]=="Buy" else -1
            ratio = leg["ratio"]
            for k in ("delta","gamma","vega","theta"):
                net[k] += sign * ratio * g[k]
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
# IV SERIES
# ─────────────────────────────────────────────────────────────────────────────

def get_iv_series_live(index, strike, expiry_label, cp,
                        tf_minutes=5, date_str=None):
    _validate_leg(index, strike, expiry_label, cp)
    df   = _get_candles(index, strike, expiry_label, cp, tf_minutes, date_str)
    spot = get_spot_price(index)
    T    = _days_to_expiry(expiry_label, index)
    rows = []
    for ts, row in df.iterrows():
        try:
            iv = implied_volatility(row["close"], spot, strike,
                                    T, RISK_FREE_RATE, cp)
            rows.append({"time": ts, "iv_pct": round(iv*100, 2)})
        except Exception:
            rows.append({"time": ts, "iv_pct": 0.0})
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# MULTIPLIER SERIES
# ─────────────────────────────────────────────────────────────────────────────

def get_multiplier_series_live(sx_strike, sx_expiry, n_strike, n_expiry,
                                interval=1, date_str=None):
    for idx, stk, exp, cp in [
        ("SENSEX", sx_strike, sx_expiry, "CE"),
        ("SENSEX", sx_strike, sx_expiry, "PE"),
        ("NIFTY",  n_strike,  n_expiry,  "CE"),
        ("NIFTY",  n_strike,  n_expiry,  "PE"),
    ]:
        _validate_leg(idx, stk, exp, cp)

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
