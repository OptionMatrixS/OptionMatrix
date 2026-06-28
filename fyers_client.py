"""fyers_client.py — all Fyers API v3 logic for Option Matrix.

Responsibilities:
  * Auto-generate the daily access token via TOTP (no manual pasting).
  * Cache the token in session_state (warm) and a dated JSON file (best effort).
  * Build correct Fyers option symbols from exchange expiry data.
  * Fetch quotes (batch), candles, and option chains.
  * Pure-Python Black-Scholes pricing / IV / Greeks (no scipy).
  * Report market open/closed status in IST.
  * Resolve lot sizes dynamically from Fyers, with verified fallbacks.

SECURITY NOTE: this stores the TOTP seed + PIN in Streamlit secrets. That makes
those secrets equivalent to full account access — keep the repo private and, if
Fyers supports it, use a data-only API app since this platform never places
orders.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from datetime import datetime, date

import requests

try:
    import pyotp
except Exception:  # pragma: no cover - present in requirements on deploy
    pyotp = None

try:
    from fyers_apiv3 import fyersModel
except Exception:  # pragma: no cover
    fyersModel = None

import streamlit as st
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TOKEN_FILE = "fyers_token.json"
REDIRECT_URI = "http://127.0.0.1:8080/"
RISK_FREE = 0.065  # ~6.5% annual; used for Greeks/IV

# Verified CURRENT lot sizes (NSE/BSE, effective Jan-2026 series). Used only as
# a fallback — get_lot_size() prefers the live value from Fyers per contract,
# because NSE re-derives these roughly quarterly.
LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "SENSEX": 20,
}

# Underlying index symbols for the option-chain call.
INDEX_SYMBOLS = {
    "NIFTY": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "SENSEX": "BSE:SENSEX-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
}

# Default safety-ladder strike interval per index.
STRIKE_INTERVAL = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "SENSEX": 100,
}

# Timeframe label -> Fyers resolution code.
TIMEFRAMES = {"1m": "1", "5m": "5", "15m": "15", "1h": "60"}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MONTH_NO = {m: i + 1 for i, m in enumerate(_MONTHS)}

IST = "Asia/Kolkata"


# ---------------------------------------------------------------------------
# Secrets helpers
# ---------------------------------------------------------------------------
def _secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


def _creds() -> dict:
    return {
        "client_id": _secret("FYERS_CLIENT_ID"),
        "secret_key": _secret("FYERS_SECRET_KEY"),
        "username": _secret("FYERS_USERNAME"),
        "pin": _secret("FYERS_PIN"),
        "totp_key": _secret("FYERS_TOTP_KEY"),
    }


def _b64(s: str) -> str:
    return base64.b64encode(str(s).encode()).decode()


# ---------------------------------------------------------------------------
# Market status (always IST, never server-local time)
# ---------------------------------------------------------------------------
def ist_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST).replace(tzinfo=None)


def market_status():
    """Return (is_open: bool, ist_now_ts). Open = weekday 09:15-15:30 IST."""
    now = ist_now()
    if now.weekday() >= 5:  # Sat/Sun
        return False, now
    t = now.time()
    open_t = datetime.strptime("09:15", "%H:%M").time()
    close_t = datetime.strptime("15:30", "%H:%M").time()
    return (open_t <= t <= close_t), now


# ---------------------------------------------------------------------------
# TOTP auto-login (5-step vagator flow)
# ---------------------------------------------------------------------------
def _totp_login() -> str:
    """Run the full TOTP login and return a fresh access_token string."""
    if pyotp is None:
        raise RuntimeError("pyotp not installed. Add 'pyotp' to requirements.txt.")
    c = _creds()
    missing = [k for k, v in c.items() if not v]
    if missing:
        raise RuntimeError("Missing Fyers secrets: " + ", ".join(missing))

    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})

    # Step 1 — send login OTP
    r1 = s.post(
        "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
        json={"fy_id": _b64(c["username"]), "app_id": "2"},
        timeout=15,
    )
    j1 = r1.json()
    request_key = j1.get("request_key")
    if not request_key:
        raise RuntimeError(f"Step 1 (send OTP) failed: {j1}")

    # Step 2 — verify TOTP
    otp = pyotp.TOTP(c["totp_key"]).now()
    r2 = s.post(
        "https://api-t2.fyers.in/vagator/v2/verify_otp",
        json={"request_key": request_key, "otp": otp},
        timeout=15,
    )
    j2 = r2.json()
    request_key = j2.get("request_key")
    if not request_key:
        raise RuntimeError(
            f"Step 2 (verify TOTP) failed — FYERS_TOTP_KEY is likely wrong "
            f"(must be the Base32 secret, not a 6-digit code): {j2}"
        )

    # Step 3 — verify PIN
    r3 = s.post(
        "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
        json={"request_key": request_key, "identity_type": "pin",
              "identifier": _b64(c["pin"])},
        timeout=15,
    )
    j3 = r3.json()
    access = j3.get("data", {}).get("access_token")
    if not access:
        raise RuntimeError(f"Step 3 (verify PIN) failed — check FYERS_PIN: {j3}")

    # Step 4 — request auth code
    app_prefix = c["client_id"].split("-")[0]
    r4 = s.post(
        "https://api-t1.fyers.in/api/v3/token",
        headers={"Authorization": f"Bearer {access}",
                 "Content-Type": "application/json"},
        json={
            "fyers_id": c["username"],
            "app_id": app_prefix,
            "redirect_uri": REDIRECT_URI,
            "appType": "100",
            "code_challenge": "",
            "state": "sample",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True,
        },
        timeout=15,
    )
    j4 = r4.json()
    url = j4.get("Url") or j4.get("url") or ""
    if "auth_code=" not in url:
        if "redirect" in json.dumps(j4).lower():
            raise RuntimeError(
                "Step 4 failed: redirect URL mismatch. The Redirect URL in your "
                "Fyers app dashboard must be exactly " + REDIRECT_URI + f". {j4}"
            )
        raise RuntimeError(f"Step 4 (auth code) failed: {j4}")
    auth_code = url.split("auth_code=")[1].split("&")[0]

    # Step 5 — validate auth code -> access token
    app_id_hash = hashlib.sha256(
        f"{c['client_id']}:{c['secret_key']}".encode()
    ).hexdigest()
    r5 = s.post(
        "https://api-t1.fyers.in/api/v3/validate-authcode",
        json={"grant_type": "authorization_code",
              "appIdHash": app_id_hash, "code": auth_code},
        timeout=15,
    )
    j5 = r5.json()
    token = j5.get("access_token")
    if not token:
        raise RuntimeError(f"Step 5 (validate authcode) failed: {j5}")
    return token


# ---------------------------------------------------------------------------
# Token cache: session_state (warm) -> dated file -> fresh login
# ---------------------------------------------------------------------------
def get_access_token(force: bool = False) -> str:
    today = date.today().isoformat()

    if not force:
        if (st.session_state.get("fy_token")
                and st.session_state.get("fy_token_date") == today):
            return st.session_state["fy_token"]
        try:
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE) as fh:
                    data = json.load(fh)
                if data.get("date") == today and data.get("token"):
                    st.session_state["fy_token"] = data["token"]
                    st.session_state["fy_token_date"] = today
                    return data["token"]
        except Exception:
            pass

    token = _totp_login()
    st.session_state["fy_token"] = token
    st.session_state["fy_token_date"] = today
    st.session_state.pop("_fc", None)  # force client rebuild with new token
    try:
        with open(TOKEN_FILE, "w") as fh:
            json.dump({"date": today, "token": token}, fh)
    except Exception:
        pass  # ephemeral FS on Streamlit Cloud — session_state still holds it
    return token


def get_fyers_client(force: bool = False):
    """Return a cached FyersModel bound to today's token."""
    if fyersModel is None:
        raise RuntimeError("fyers-apiv3 not installed. Add it to requirements.txt.")
    token = get_access_token(force=force)
    fc = st.session_state.get("_fc")
    if fc is not None and st.session_state.get("_fc_token") == token and not force:
        return fc
    client_id = _creds()["client_id"]
    fc = fyersModel.FyersModel(client_id=client_id, token=token,
                               is_async=False, log_path="")
    st.session_state["_fc"] = fc
    st.session_state["_fc_token"] = token
    return fc


def refresh_token() -> str:
    """Force a brand-new token (used by the sidebar button)."""
    return get_access_token(force=True)


# ---------------------------------------------------------------------------
# Symbol building
# ---------------------------------------------------------------------------
def exchange_for(index: str) -> str:
    return "BSE" if index.upper() in ("SENSEX", "BANKEX") else "NSE"


def _date_to_code(dt: date, is_monthly: bool) -> str:
    """YYMON for monthly, YY + M(no leading zero) + DD for weekly."""
    yy = dt.strftime("%y")
    if is_monthly:
        return f"{yy}{_MONTHS[dt.month - 1]}"
    return f"{yy}{dt.month}{dt.day:02d}"


def _label_to_code(label: str) -> str:
    """Fallback parser: 'DD MON YY (W/M)' -> Fyers code. Session cache first."""
    cache = st.session_state.setdefault("code_cache", {})
    if label in cache:
        return cache[label]
    import re
    m = re.match(r"\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2,4})\s*\(([WMwm])\)", label)
    if not m:
        return label.strip()
    dd, mon, yy, wm = m.groups()
    mon = mon.upper()
    if mon not in _MONTH_NO:
        return label.strip()
    yy = yy[-2:]
    if wm.upper() == "M":
        code = f"{yy}{mon}"
    else:
        code = f"{yy}{_MONTH_NO[mon]}{int(dd):02d}"
    cache[label] = code
    return code


def build_symbol(index: str, code_or_label: str, opt_type: str, strike) -> str:
    """Build e.g. 'NSE:NIFTY26519CE23750'. Accepts a code or a raw label."""
    code = code_or_label
    if "(" in str(code_or_label) or " " in str(code_or_label).strip():
        code = _label_to_code(code_or_label)
    exch = exchange_for(index)
    root = index.upper()
    try:
        strike = int(round(float(strike)))
    except Exception:
        pass
    return f"{exch}:{root}{code}{opt_type.upper()}{strike}"


# ---------------------------------------------------------------------------
# Expiries & strikes (from live option chain)
# ---------------------------------------------------------------------------
def _parse_expiry_date(item: dict) -> date:
    raw = str(item.get("date") or item.get("expiry") or "")
    # Try DD-MM-YYYY then epoch seconds.
    for fmt in ("%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except Exception:
            continue
    try:
        return datetime.utcfromtimestamp(int(float(raw))).date()
    except Exception:
        return date.today()


def _expiry_epoch(item: dict) -> str:
    for k in ("expiry", "ts", "timestamp"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


@st.cache_resource(ttl=1800, show_spinner=False)
def get_expiries(index: str):
    """List of expiry dicts {label, code, date, epoch, is_monthly}.

    Raises on failure (never returns empty) so the empty result is not cached.
    """
    fc = get_fyers_client()
    sym = INDEX_SYMBOLS[index.upper()]
    resp = fc.optionchain(data={"symbol": sym, "strikecount": 1, "timestamp": ""})
    edata = (resp or {}).get("data", {}).get("expiryData")
    if not edata:
        raise RuntimeError(f"No expiryData for {index}: {resp}")

    rows = []
    for it in edata:
        d = _parse_expiry_date(it)
        rows.append({"date": d, "epoch": _expiry_epoch(it)})
    rows.sort(key=lambda r: r["date"])

    # Monthly = the last available expiry within each calendar month.
    last_in_month = {}
    for r in rows:
        key = (r["date"].year, r["date"].month)
        last_in_month[key] = r["date"]

    out = []
    for r in rows:
        key = (r["date"].year, r["date"].month)
        is_m = (last_in_month[key] == r["date"])
        code = _date_to_code(r["date"], is_m)
        label = (f"{r['date'].day:02d} {_MONTHS[r['date'].month - 1]} "
                 f"{r['date'].strftime('%y')} ({'M' if is_m else 'W'})")
        out.append({"label": label, "code": code, "date": r["date"],
                    "epoch": r["epoch"], "is_monthly": is_m})
        st.session_state.setdefault("code_cache", {})[label] = code
    st.session_state[f"exp_{index.upper()}"] = out
    return out


def expiry_labels(index: str):
    return [e["label"] for e in get_expiries(index)]


def find_expiry(index: str, label: str):
    for e in get_expiries(index):
        if e["label"] == label:
            return e
    return None


@st.cache_resource(ttl=1800, show_spinner=False)
def get_chain(index: str, epoch: str):
    """Full optionsChain list for a given expiry epoch (strikecount=0 = all)."""
    fc = get_fyers_client()
    sym = INDEX_SYMBOLS[index.upper()]
    resp = fc.optionchain(data={"symbol": sym, "strikecount": 0,
                                "timestamp": str(epoch)})
    chain = (resp or {}).get("data", {}).get("optionsChain")
    if chain is None:
        raise RuntimeError(f"No optionsChain for {index}@{epoch}: {resp}")
    return chain


def get_strikes(index: str, label: str):
    """Sorted unique strike list for an expiry label."""
    e = find_expiry(index, label)
    if not e:
        return []
    code = e["code"]
    key = f"stk_{index.upper()}_{code}"
    if key in st.session_state:
        return st.session_state[key]
    chain = get_chain(index, e["epoch"])
    strikes = sorted({_to_float(c.get("strike_price"))
                      for c in chain if c.get("strike_price") not in (None, "")})
    strikes = [int(s) for s in strikes if s and s > 0]
    st.session_state[key] = strikes
    return strikes


def underlying_ltp(index: str) -> float:
    q = get_quote(INDEX_SYMBOLS[index.upper()])
    return q.get("ltp", 0.0)


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------
def _to_float(v, default=0.0) -> float:
    """Robust float: handles '22,800' strings and None."""
    if v is None:
        return default
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def get_quotes(symbols) -> dict:
    """Batch quote. Returns {symbol: {ltp, prev_close, bid, ask, high, low,
    open, volume, oi}}. LTP falls back to prev_close when the market is closed
    (Fyers returns lp=0)."""
    if not symbols:
        return {}
    syms = [s for s in symbols if s]
    fc = get_fyers_client()
    resp = fc.quotes(data={"symbols": ",".join(syms)})
    out = {}
    for row in (resp or {}).get("d", []) or []:
        name = row.get("n")
        v = row.get("v", {}) or {}
        prev = _to_float(v.get("prev_close_price"))
        lp = _to_float(v.get("lp"))
        out[name] = {
            "ltp": lp if lp else prev,
            "raw_ltp": lp,
            "prev_close": prev,
            "bid": _to_float(v.get("bid")),
            "ask": _to_float(v.get("ask")),
            "high": _to_float(v.get("high_price")),
            "low": _to_float(v.get("low_price")),
            "open": _to_float(v.get("open_price")),
            "volume": _to_float(v.get("volume")),
            "oi": _to_float(v.get("oi")),
        }
    # Ensure every requested symbol has an entry.
    for s in syms:
        out.setdefault(s, {"ltp": 0.0, "raw_ltp": 0.0, "prev_close": 0.0,
                           "bid": 0.0, "ask": 0.0, "high": 0.0, "low": 0.0,
                           "open": 0.0, "volume": 0.0, "oi": 0.0})
    return out


def get_quote(symbol: str) -> dict:
    return get_quotes([symbol]).get(symbol, {"ltp": 0.0})


# ---------------------------------------------------------------------------
# Candles
# ---------------------------------------------------------------------------
def get_candles(symbol: str, date_from, date_to, resolution: str = "1") -> pd.DataFrame:
    """OHLCV DataFrame with IST timestamps. resolution = Fyers code ('1','5'...)."""
    fc = get_fyers_client()
    if hasattr(date_from, "isoformat"):
        date_from = date_from.isoformat()
    if hasattr(date_to, "isoformat"):
        date_to = date_to.isoformat()
    resp = fc.history(data={"symbol": symbol, "resolution": str(resolution),
                            "date_format": "1", "range_from": date_from,
                            "range_to": date_to, "cont_flag": "1"})
    candles = (resp or {}).get("candles") or []
    if not candles:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    # Unix seconds (UTC) -> IST naive.
    df["ts"] = (pd.to_datetime(df["ts"], unit="s")
                .dt.tz_localize("UTC").dt.tz_convert(IST).dt.tz_localize(None))
    return df


def resolution_for(timeframe_label: str) -> str:
    return TIMEFRAMES.get(timeframe_label, "1")


# ---------------------------------------------------------------------------
# Lot size (live first, fallback to verified table)
# ---------------------------------------------------------------------------
def get_lot_size(index: str, symbol: str = None) -> int:
    idx = index.upper()
    if symbol:
        try:
            chain = None
            exps = st.session_state.get(f"exp_{idx}")
            if exps:
                chain = get_chain(idx, exps[0]["epoch"])
            if chain:
                for c in chain:
                    if str(c.get("symbol")) == symbol:
                        ls = int(_to_float(c.get("lot_size")
                                           or c.get("lotsize") or c.get("ls")))
                        if ls > 0:
                            return ls
        except Exception:
            pass
    return LOT_SIZES.get(idx, 1)


# ---------------------------------------------------------------------------
# Black-Scholes (pure Python) — pricing, Greeks, implied volatility
# ---------------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(spot, strike, t, sigma, opt_type, r=RISK_FREE):
    """European option price. t in years."""
    if t <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        intrinsic = (max(spot - strike, 0.0) if opt_type.upper() == "CE"
                     else max(strike - spot, 0.0))
        return intrinsic
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if opt_type.upper() == "CE":
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def bs_greeks(spot, strike, t, sigma, opt_type, r=RISK_FREE) -> dict:
    """Delta, Gamma, Vega (per 1% vol), Theta (per day)."""
    if t <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    sq = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * sq)
    d2 = d1 - sigma * sq
    pdf = _norm_pdf(d1)
    if opt_type.upper() == "CE":
        delta = _norm_cdf(d1)
        theta = (-(spot * pdf * sigma) / (2 * sq)
                 - r * strike * math.exp(-r * t) * _norm_cdf(d2))
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-(spot * pdf * sigma) / (2 * sq)
                 + r * strike * math.exp(-r * t) * _norm_cdf(-d2))
    gamma = pdf / (spot * sigma * sq)
    vega = spot * pdf * sq            # per 1.00 vol
    return {"delta": delta, "gamma": gamma,
            "vega": vega / 100.0,     # per 1% vol
            "theta": theta / 365.0}   # per calendar day


def implied_vol(price, spot, strike, t, opt_type, r=RISK_FREE):
    """IV via bisection. Returns sigma (decimal) or None if no solution."""
    price = _to_float(price)
    if price <= 0 or t <= 0 or spot <= 0 or strike <= 0:
        return None
    intrinsic = (max(spot - strike, 0.0) if opt_type.upper() == "CE"
                 else max(strike - spot, 0.0))
    if price < intrinsic - 1e-6:
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        diff = bs_price(spot, strike, t, mid, opt_type, r) - price
        if abs(diff) < 1e-4:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def years_to_expiry(expiry_date: date) -> float:
    """Calendar years from now (IST) to 15:30 on the expiry date."""
    now = ist_now()
    exp_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day, 15, 30)
    secs = (exp_dt - now.to_pydatetime()).total_seconds()
    return max(secs, 0.0) / (365.0 * 24 * 3600)


# ---------------------------------------------------------------------------
# Leg helpers (shared by Spread Chart, Tracker, Backtest, Strategy Builder)
# A "leg" dict uses: index, expiry (label), strike, opt_type (CE/PE),
# side (Buy/Sell), and ratio or lots.
# ---------------------------------------------------------------------------
def leg_to_symbol(leg: dict) -> str:
    idx = leg.get("index", "NIFTY")
    label = leg.get("expiry", "")
    e = find_expiry(idx, label) if label else None
    code = e["code"] if e else label
    return build_symbol(idx, code, leg.get("opt_type", "CE"), leg.get("strike", 0))


def leg_sign(leg: dict) -> float:
    return 1.0 if str(leg.get("side", "Buy")).lower().startswith("b") else -1.0


def spread_value(legs, quotes: dict) -> float:
    """Net spread = Σ sign * ratio * LTP across legs (from a quotes dict)."""
    total = 0.0
    for lg in legs:
        sym = leg_to_symbol(lg)
        ltp = quotes.get(sym, {}).get("ltp", 0.0)
        total += leg_sign(lg) * float(lg.get("ratio", 1)) * ltp
    return total


def net_premium(legs, quotes: dict) -> float:
    """Net debit(+)/credit(-) using LTP as the entry premium proxy."""
    return spread_value(legs, quotes)


# ---------------------------------------------------------------------------
# Payoff engine (shared by Spread Chart + Strategy Builder)
# Each payoff "leg" dict needs: opt_type (CE/PE), strike, side (Buy/Sell),
# qty (contracts or ratio), premium (entry price in points).
# ---------------------------------------------------------------------------
def _intrinsic(opt_type: str, strike: float, spot: float) -> float:
    if opt_type.upper() == "CE":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def payoff_at(legs, spot: float) -> float:
    total = 0.0
    for lg in legs:
        sign = 1.0 if str(lg.get("side", "Buy")).lower().startswith("b") else -1.0
        qty = float(lg.get("qty", 1))
        prem = float(lg.get("premium", 0.0))
        total += sign * qty * (_intrinsic(lg.get("opt_type", "CE"),
                                          float(lg.get("strike", 0)), spot) - prem)
    return total


def payoff_curve(legs, spots):
    return [payoff_at(legs, s) for s in spots]


def payoff_stats(spots, pnl):
    """Return (max_profit, max_loss, breakevens[list])."""
    if not pnl:
        return 0.0, 0.0, []
    mx, mn = max(pnl), min(pnl)
    bes = []
    for i in range(1, len(pnl)):
        a, b = pnl[i - 1], pnl[i]
        if (a <= 0 <= b) or (a >= 0 >= b):
            if b != a:
                x = spots[i - 1] + (spots[i] - spots[i - 1]) * (0 - a) / (b - a)
            else:
                x = spots[i]
            x = round(x, 1)
            if not bes or abs(x - bes[-1]) > max(1.0, abs(x) * 0.001):
                bes.append(x)
    return mx, mn, bes
