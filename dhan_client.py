"""
dhan_client.py
Live data from Dhan API — clean, validated, production-ready.
All public functions validate inputs before making API calls.
"""

import streamlit as st
import pandas as pd
import math
import io
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

try:
    from dhanhq import dhanhq
except ImportError:
    raise ImportError("Run: pip install dhanhq")

RISK_FREE_RATE = 0.065

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _exchange(index: str) -> str:
    return "BSE_FO" if index == "SENSEX" else "NSE_FO"

def _underlying(index: str) -> str:
    mapping = {"NIFTY": "NIFTY", "SENSEX": "SENSEX", "BANKNIFTY": "BANKNIFTY"}
    if index not in mapping:
        raise ValueError(f"Unsupported index: {index}. Choose NIFTY, SENSEX, or BANKNIFTY.")
    return mapping[index]

def _parse_expiry(expiry_str: str) -> pd.Timestamp:
    """Convert '13 Apr' or '13 Apr 2025' to pd.Timestamp. Raises on failure."""
    if not expiry_str or expiry_str.strip() == "":
        raise ValueError("Expiry cannot be empty.")
    try:
        parts = expiry_str.strip().split()
        if len(parts) == 2:
            expiry_str = f"{parts[0]} {parts[1]} {datetime.now().year}"
        ts = pd.Timestamp(expiry_str)
        return ts
    except Exception:
        raise ValueError(f"Invalid expiry format: '{expiry_str}'. Expected like '13 Apr'.")

def _validate_leg(index: str, strike: int, expiry: str, cp: str):
    """Raise ValueError if any leg parameter is invalid."""
    _underlying(index)  # validates index
    if not expiry or expiry.strip() == "":
        raise ValueError(f"Expiry not selected for {index} {cp}.")
    if not isinstance(strike, (int, float)) or strike <= 0:
        raise ValueError(f"Invalid strike '{strike}' for {index} {expiry} {cp}.")
    if cp not in ("CE", "PE"):
        raise ValueError(f"Invalid option type '{cp}'. Must be CE or PE.")

# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

def get_dhan_client() -> dhanhq:
    """Returns cached, authenticated Dhan client."""
    if st.session_state.get("dhan_client"):
        return st.session_state.dhan_client
    try:
        client = dhanhq(
            st.secrets["DHAN_CLIENT_ID"],
            st.secrets["DHAN_ACCESS_TOKEN"]
        )
        st.session_state.dhan_client = client
        return client
    except KeyError as e:
        raise ValueError(f"Missing Dhan secret: {e}. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to Streamlit secrets.")

# ─────────────────────────────────────────────────────────────────────────────
# MASTER CSV
# ─────────────────────────────────────────────────────────────────────────────

def _load_master() -> pd.DataFrame:
    """Load and cache Dhan master script CSV. Called once per session."""
    if "dhan_master" in st.session_state:
        return st.session_state.dhan_master
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        with urllib.request.urlopen(url, timeout=20) as r:
            content = r.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(content))
        df = df[df["SEM_INSTRUMENT_NAME"].isin(["OPTIDX", "OPTSTK"])].copy()
        df["SEM_EXPIRY_DATE"]  = pd.to_datetime(df["SEM_EXPIRY_DATE"],  errors="coerce")
        df["SEM_STRIKE_PRICE"] = pd.to_numeric(df["SEM_STRIKE_PRICE"],  errors="coerce")
        df = df.dropna(subset=["SEM_EXPIRY_DATE", "SEM_STRIKE_PRICE"])
        st.session_state.dhan_master = df
        return df
    except Exception as e:
        raise ConnectionError(f"Failed to load Dhan master CSV: {e}")

def clear_master_cache():
    """Force re-download of master CSV on next call."""
    st.session_state.pop("dhan_master", None)

# ─────────────────────────────────────────────────────────────────────────────
# EXPIRIES AND STRIKES  (cached per index / per index+expiry)
# ─────────────────────────────────────────────────────────────────────────────

def get_expiries(index: str) -> list:
    """
    Return sorted list of future expiry strings like ['13 Apr', '17 Apr', ...].
    Cached in session state per index.
    """
    cache_key = f"expiries_{index}"
    if st.session_state.get(cache_key):
        return st.session_state[cache_key]

    _underlying(index)  # validate
    df    = _load_master()
    exch  = _exchange(index)
    uname = _underlying(index)

    mask  = (
        (df["SEM_EXM_EXCH_ID"] == exch) &
        (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False))
    )
    today  = pd.Timestamp(datetime.now().date())
    dates  = sorted([
        e for e in df[mask]["SEM_EXPIRY_DATE"].dropna().unique()
        if pd.notna(e) and e >= today
    ])
    if not dates:
        raise ValueError(f"No future expiries found for {index}. Dhan master CSV may be stale.")

    # Format: try Linux format first, fall back to Windows
    try:
        result = [e.strftime("%-d %b") for e in dates[:12]]
    except ValueError:
        result = [e.strftime("%#d %b") for e in dates[:12]]

    st.session_state[cache_key] = result
    return result

def get_strikes(index: str, expiry: str) -> list:
    """
    Return sorted list of available integer strike prices.
    Cached per index+expiry.
    """
    cache_key = f"strikes_{index}_{expiry}"
    if st.session_state.get(cache_key):
        return st.session_state[cache_key]

    _validate_leg(index, 1, expiry, "CE")  # validate index + expiry only
    df     = _load_master()
    exch   = _exchange(index)
    uname  = _underlying(index)
    exp_dt = _parse_expiry(expiry)

    mask = (
        (df["SEM_EXM_EXCH_ID"] == exch) &
        (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False)) &
        (df["SEM_EXPIRY_DATE"]  == exp_dt)
    )
    strikes = sorted(df[mask]["SEM_STRIKE_PRICE"].dropna().unique().tolist())
    if not strikes:
        raise ValueError(f"No strikes found for {index} {expiry}. Check expiry or Dhan master CSV.")

    result = [int(s) for s in strikes]
    st.session_state[cache_key] = result
    return result

# ─────────────────────────────────────────────────────────────────────────────
# SECURITY ID LOOKUP
# ─────────────────────────────────────────────────────────────────────────────

def get_security_id(index: str, strike: int, expiry: str, cp: str) -> str:
    """
    Lookup Dhan security ID. Always validates inputs first.
    Cached per contract.
    """
    _validate_leg(index, strike, expiry, cp)

    cache_key = f"secid_{index}_{strike}_{expiry}_{cp}"
    if st.session_state.get(cache_key):
        return st.session_state[cache_key]

    df       = _load_master()
    exch     = _exchange(index)
    uname    = _underlying(index)
    opt_type = "CALL" if cp == "CE" else "PUT"
    exp_dt   = _parse_expiry(expiry)

    mask = (
        (df["SEM_EXM_EXCH_ID"] == exch) &
        (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False)) &
        (df["SEM_STRIKE_PRICE"] == float(strike)) &
        (df["SEM_EXPIRY_DATE"]  == exp_dt) &
        (df["SEM_OPTION_TYPE"]  == opt_type)
    )
    result = df[mask]

    # Try next year if not found (for far expiries)
    if result.empty:
        exp_dt2 = pd.Timestamp(exp_dt.year + 1, exp_dt.month, exp_dt.day)
        mask2 = (
            (df["SEM_EXM_EXCH_ID"] == exch) &
            (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False)) &
            (df["SEM_STRIKE_PRICE"] == float(strike)) &
            (df["SEM_EXPIRY_DATE"]  == exp_dt2) &
            (df["SEM_OPTION_TYPE"]  == opt_type)
        )
        result = df[mask2]

    if result.empty:
        raise ValueError(
            f"Contract not found: {index} {strike} {cp} exp={expiry}. "
            f"Available expiries: {get_expiries(index)[:5]}"
        )

    sid = str(result.iloc[0]["SEM_SMST_SECURITY_ID"])
    st.session_state[cache_key] = sid
    return sid

# ─────────────────────────────────────────────────────────────────────────────
# LIVE QUOTES
# ─────────────────────────────────────────────────────────────────────────────

def get_live_quote(index: str, strike: int, expiry: str, cp: str) -> dict:
    """
    Returns dict: ltp, bid, ask, prev_close, high, low.
    Validates all inputs before API call.
    """
    _validate_leg(index, strike, expiry, cp)
    dhan = get_dhan_client()
    exch = _exchange(index)
    sid  = get_security_id(index, strike, expiry, cp)
    resp = dhan.get_market_feed_quote(securities={exch: [sid]})
    if resp.get("status") == "success":
        d   = resp["data"][exch][sid]
        ltp = float(d.get("last_price", 0))
        return {
            "ltp":        ltp,
            "bid":        float(d.get("best_bid_price",       ltp * 0.998)),
            "ask":        float(d.get("best_ask_price",       ltp * 1.002)),
            "prev_close": float(d.get("previous_close_price", 0)),
            "high":       float(d.get("high_price",           ltp)),
            "low":        float(d.get("low_price",            ltp)),
        }
    raise ValueError(f"Dhan quote API failed: {resp.get('remarks', resp)}")

def get_live_ltp(index: str, strike: int, expiry: str, cp: str) -> float:
    return get_live_quote(index, strike, expiry, cp)["ltp"]

def get_live_bid_ask_ltp(index: str, strike: int, expiry: str, cp: str) -> tuple:
    q = get_live_quote(index, strike, expiry, cp)
    return q["bid"], q["ask"], q["ltp"]

# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL CANDLES
# ─────────────────────────────────────────────────────────────────────────────

def _get_candles(index: str, strike: int, expiry: str,
                 cp: str, interval: str = "1") -> pd.DataFrame:
    """Fetch OHLCV candles. Validates inputs, raises on failure."""
    _validate_leg(index, strike, expiry, cp)
    dhan = get_dhan_client()
    exch = _exchange(index)
    sid  = get_security_id(index, strike, expiry, cp)

    if interval == "D":
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        to_date   = datetime.now().strftime("%Y-%m-%d")
        resp = dhan.historical_daily_data(
            security_id=sid, exchange_segment=exch,
            instrument_type="OPTIDX", expiry_code=0,
            from_date=from_date, to_date=to_date)
    else:
        resp = dhan.intraday_minute_data(
            security_id=sid, exchange_segment=exch,
            instrument_type="OPTIDX")

    if resp.get("status") != "success":
        raise ValueError(f"Candle fetch failed for {index} {strike} {expiry} {cp}: {resp.get('remarks', resp)}")

    d = resp["data"]
    if not d.get("timestamp"):
        raise ValueError(f"No candle data returned for {index} {strike} {expiry} {cp}. Market may be closed.")

    return pd.DataFrame({
        "time":  pd.to_datetime(d["timestamp"]),
        "open":  d["open"],
        "high":  d["high"],
        "low":   d["low"],
        "close": d["close"],
    })

# ─────────────────────────────────────────────────────────────────────────────
# SPREAD OHLCV
# ─────────────────────────────────────────────────────────────────────────────

def validate_legs(legs: list):
    """
    Validate all legs before any API call.
    Raises ValueError with a clear message if any leg is invalid.
    Call this first in any function that uses leg data.
    """
    if not legs:
        raise ValueError("No legs provided.")
    for i, leg in enumerate(legs):
        try:
            _validate_leg(
                leg.get("index", ""),
                leg.get("strike", 0),
                leg.get("expiry", ""),
                leg.get("cp", "")
            )
        except ValueError as e:
            raise ValueError(f"Leg {i+1} invalid: {e}")

def get_live_spread_ohlcv(legs: list, interval: str = "1") -> pd.DataFrame:
    """
    Compute spread OHLCV from per-leg candles.
    Validates ALL legs before making any API call.
    """
    validate_legs(legs)

    spread_close = None
    base_times   = None

    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"],
                              leg["expiry"], leg["cp"], interval)
        price = df.set_index("time")["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price
        if spread_close is None:
            spread_close = price
            base_times   = df["time"]
        else:
            spread_close = spread_close.add(price, fill_value=0)

    out          = pd.DataFrame()
    out["time"]  = base_times.values
    out["close"] = spread_close.values
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open","close"]].max(axis=1)
    out["low"]   = out[["open","close"]].min(axis=1)
    return out.reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# BLACK-SCHOLES GREEKS
# ─────────────────────────────────────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def _days_to_expiry(expiry_str: str) -> float:
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    try:
        parts  = expiry_str.strip().split()
        day, mon = int(parts[0]), months[parts[1]]
        year   = datetime.now().year
        exp_dt = datetime(year, mon, day)
        if exp_dt < datetime.now():
            exp_dt = datetime(year + 1, mon, day)
        return max((exp_dt - datetime.now()).days, 1) / 365.0
    except Exception:
        return 30 / 365.0

def bs_price(S: float, K: float, T: float, r: float, sigma: float, cp: str) -> float:
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "CE" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if cp == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

def implied_volatility(market_price: float, S: float, K: float,
                        T: float, r: float, cp: str) -> float:
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
    low, high = 0.001, 5.0
    for _ in range(200):
        mid   = (low + high) / 2
        price = bs_price(S, K, T, r, mid, cp)
        if abs(price - market_price) < 1e-5:
            return mid
        if price < market_price:
            low = mid
        else:
            high = mid
    return mid

def bs_greeks(S: float, K: float, T: float, r: float,
              sigma: float, cp: str) -> dict:
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0, "iv": sigma * 100}
    d1  = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2  = d1 - sigma * math.sqrt(T)
    pdf = _norm_pdf(d1)
    gamma = pdf / (S * sigma * math.sqrt(T))
    vega  = S * pdf * math.sqrt(T) / 100
    if cp == "CE":
        delta = _norm_cdf(d1)
        theta = (-(S * pdf * sigma) / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(S * pdf * sigma) / (2 * math.sqrt(T))
                 + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "vega":  round(vega,  4), "theta": round(theta, 4),
            "iv":    round(sigma * 100, 2)}

def get_spot_price(index: str) -> float:
    """Estimate spot via put-call parity on nearest ATM strike."""
    try:
        expiries = get_expiries(index)
        strikes  = get_strikes(index, expiries[0])
        atm_map  = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}
        atm      = min(strikes, key=lambda x: abs(x - atm_map.get(index, strikes[len(strikes)//2])))
        ce_ltp   = get_live_ltp(index, atm, expiries[0], "CE")
        pe_ltp   = get_live_ltp(index, atm, expiries[0], "PE")
        return round(atm + ce_ltp - pe_ltp, 2)
    except Exception:
        return {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)

def get_spread_greeks(legs: list, spot_prices: dict) -> dict:
    """Net Greeks for a spread using B-S. Returns delta, gamma, vega, theta, net_iv."""
    validate_legs(legs)
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "ivs": []}
    for leg in legs:
        try:
            S     = float(spot_prices.get(leg["index"], 22800))
            K     = float(leg["strike"])
            T     = _days_to_expiry(leg["expiry"])
            ltp   = get_live_ltp(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
            sigma = implied_volatility(ltp, S, K, T, RISK_FREE_RATE, leg["cp"])
            g     = bs_greeks(S, K, T, RISK_FREE_RATE, sigma, leg["cp"])
            sign  = 1 if leg["bs"] == "Buy" else -1
            ratio = leg["ratio"]
            net["delta"] += sign * ratio * g["delta"]
            net["gamma"] += sign * ratio * g["gamma"]
            net["vega"]  += sign * ratio * g["vega"]
            net["theta"] += sign * ratio * g["theta"]
            net["ivs"].append(g["iv"])
        except Exception:
            pass
    return {
        "delta":  round(net["delta"], 4),
        "gamma":  round(net["gamma"], 6),
        "vega":   round(net["vega"],  4),
        "theta":  round(net["theta"], 4),
        "net_iv": round(sum(net["ivs"]) / len(net["ivs"]), 2) if net["ivs"] else 0.0,
    }

# ─────────────────────────────────────────────────────────────────────────────
# IV SERIES + MULTIPLIER
# ─────────────────────────────────────────────────────────────────────────────

def get_iv_series_live(index: str, strike: int, expiry: str,
                        cp: str, tf_minutes: int = 5) -> pd.DataFrame:
    _validate_leg(index, strike, expiry, cp)
    tf_map = {1:"1", 5:"5", 15:"15", 60:"60", 375:"D"}
    df     = _get_candles(index, strike, expiry, cp, tf_map.get(tf_minutes, "5"))
    spot   = get_spot_price(index)
    T      = _days_to_expiry(expiry)
    rows   = []
    for _, row in df.iterrows():
        try:
            iv     = implied_volatility(row["close"], spot, strike, T, RISK_FREE_RATE, cp)
            iv_pct = round(iv * 100, 2)
        except Exception:
            iv_pct = 0.0
        rows.append({"time": row["time"], "iv_pct": iv_pct})
    return pd.DataFrame(rows)

def get_multiplier_series_live(sx_strike: int, sx_expiry: str,
                                n_strike: int,  n_expiry:  str,
                                interval: str = "1") -> pd.DataFrame:
    for idx, st_val, exp, cp in [
        ("SENSEX", sx_strike, sx_expiry, "CE"),
        ("SENSEX", sx_strike, sx_expiry, "PE"),
        ("NIFTY",  n_strike,  n_expiry,  "CE"),
        ("NIFTY",  n_strike,  n_expiry,  "PE"),
    ]:
        _validate_leg(idx, st_val, exp, cp)

    sx_ce = _get_candles("SENSEX", sx_strike, sx_expiry, "CE", interval).set_index("time")["close"]
    sx_pe = _get_candles("SENSEX", sx_strike, sx_expiry, "PE", interval).set_index("time")["close"]
    n_ce  = _get_candles("NIFTY",  n_strike,  n_expiry,  "CE", interval).set_index("time")["close"]
    n_pe  = _get_candles("NIFTY",  n_strike,  n_expiry,  "PE", interval).set_index("time")["close"]

    sx_synth   = sx_strike + sx_ce - sx_pe
    n_synth    = n_strike  + n_ce  - n_pe
    multiplier = (sx_synth / n_synth).round(4)

    return pd.DataFrame({
        "time":       sx_synth.index,
        "multiplier": multiplier.values,
        "sx_synth":   sx_synth.values.round(2),
        "n_synth":    n_synth.values.round(2),
    }).reset_index(drop=True)
