"""
Fyers Data Helpers
Handles:
  - Symbol building (label → code → symbol) — the #1 bug fix
  - LTP fetch with prev_close fallback
  - Option chain fetch
  - Expiry list fetch
"""

import re
import pandas as pd
import streamlit as st
from typing import Optional


# ─────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 35, "SENSEX": 20, "FINNIFTY": 40}

EXCHANGES = {"NIFTY": "NSE", "BANKNIFTY": "NSE", "FINNIFTY": "NSE", "SENSEX": "BSE"}

MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}
MONTH_ABBR = {
    "01": "JAN", "02": "FEB", "03": "MAR", "04": "APR",
    "05": "MAY", "06": "JUN", "07": "JUL", "08": "AUG",
    "09": "SEP", "10": "OCT", "11": "NOV", "12": "DEC",
}


# ─────────────────────────────────────────────────────
# LABEL → CODE (THE CRITICAL FIX)
# ─────────────────────────────────────────────────────

def label_to_code(label: str, index: str = "NIFTY") -> str:
    """
    Convert Fyers expiry label to symbol code segment.

    Examples:
      "19 MAY 26 (W)" → "260519"   (weekly)
      "29 MAY 26 (M)" → "26MAY"    (monthly)
      "02 JUN 26 (W)" → "260602"

    Works WITHOUT needing session state / option chain cache.
    Falls back to cache if available.
    """
    label = label.strip()

    # Try cache first (populated after option chain fetch)
    cache = st.session_state.get("expiry_code_cache", {})
    cache_key = f"{index}|{label}"
    if cache_key in cache:
        return cache[cache_key]

    # Parse directly from label string
    # Expected format: "DD MON YY (W)" or "DD MON YY (M)"
    m = re.match(
        r"(\d{1,2})\s+([A-Z]{3})\s+(\d{2,4})\s*\((W|M)\)",
        label,
        re.IGNORECASE,
    )
    if not m:
        # Last resort: return label (will cause invalid symbol — better than crash)
        st.warning(f"⚠️ Could not parse expiry label: '{label}'")
        return label

    dd  = m.group(1).zfill(2)
    mon = m.group(2).upper()
    yy  = m.group(3)[-2:]          # last 2 digits of year
    typ = m.group(4).upper()        # W or M

    mm = MONTH_MAP.get(mon, "00")

    if typ == "M":
        # Monthly: YYMON  e.g. "26MAY"
        code = f"{yy}{mon}"
    else:
        # Weekly:  YYMMDD e.g. "260519"
        code = f"{yy}{mm}{dd}"

    # Store in cache
    cache[cache_key] = code
    st.session_state["expiry_code_cache"] = cache
    return code


def build_symbol(index: str, expiry_label: str, strike: int, opt_type: str) -> str:
    """
    Build a valid Fyers option symbol.
    e.g. "NSE:NIFTY26519CE23750" or "BSE:SENSEX26MAYCE79000"
    """
    exchange = EXCHANGES.get(index.upper(), "NSE")
    code     = label_to_code(expiry_label, index)
    ot       = opt_type.upper()   # CE or PE
    return f"{exchange}:{index.upper()}{code}{ot}{int(strike)}"


def build_futures_symbol(index: str, expiry_label: str) -> str:
    exchange = EXCHANGES.get(index.upper(), "NSE")
    code     = label_to_code(expiry_label, index)
    return f"{exchange}:{index.upper()}{code}FUT"


# ─────────────────────────────────────────────────────
# LTP FETCH
# ─────────────────────────────────────────────────────

def fetch_ltp(fyers, symbols: list[str]) -> dict[str, dict]:
    """
    Fetch LTP (and prev_close) for a list of symbols.
    Returns dict: symbol → {ltp, prev_close, bid, ask, open_price}
    Falls back to prev_close when market is closed (ltp == 0).
    """
    if not fyers or not symbols:
        return {}

    try:
        resp = fyers.quotes({"symbols": ",".join(symbols)})
        if resp.get("s") != "ok":
            return {}

        result = {}
        for item in resp.get("d", []):
            v = item.get("v", {})
            sym = item.get("n", "")
            raw_ltp   = float(v.get("lp", 0) or 0)
            prev_close = float(v.get("prev_close_price", 0) or 0)
            bid        = float(v.get("bid", 0) or 0)
            ask        = float(v.get("ask", 0) or 0)
            open_p     = float(v.get("open_price", 0) or 0)

            # Fallback: use prev_close when market closed
            ltp = raw_ltp if raw_ltp > 0 else prev_close

            result[sym] = {
                "ltp": ltp,
                "raw_ltp": raw_ltp,
                "prev_close": prev_close,
                "bid": bid,
                "ask": ask,
                "open": open_p,
                "market_closed": raw_ltp == 0,
            }
        return result
    except Exception as e:
        st.error(f"LTP fetch error: {e}")
        return {}


def fetch_single_ltp(fyers, symbol: str) -> float:
    """Quick helper — returns just the LTP float."""
    data = fetch_ltp(fyers, [symbol])
    return data.get(symbol, {}).get("ltp", 0.0)


def is_market_closed(ltp_data: dict) -> bool:
    """True if ANY symbol returned market_closed flag."""
    return any(v.get("market_closed", False) for v in ltp_data.values())


# ─────────────────────────────────────────────────────
# INDEX SPOT
# ─────────────────────────────────────────────────────

INDEX_SYMBOLS = {
    "NIFTY":     "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "SENSEX":    "BSE:SENSEX-INDEX",
    "FINNIFTY":  "NSE:FINNIFTY-INDEX",
}

def fetch_spot(fyers, index: str) -> float:
    sym = INDEX_SYMBOLS.get(index.upper())
    if not sym:
        return 0.0
    data = fetch_ltp(fyers, [sym])
    return data.get(sym, {}).get("ltp", 0.0)


# ─────────────────────────────────────────────────────
# OPTION CHAIN
# ─────────────────────────────────────────────────────

def fetch_option_chain(fyers, symbol: str, strike_count: int = 0) -> dict:
    """
    Fetch full option chain from Fyers.
    symbol e.g. "NIFTY", "SENSEX"
    strike_count=0 → all strikes
    Returns raw Fyers response dict.
    """
    try:
        resp = fyers.optionchain({
            "symbol": symbol,
            "strikecount": strike_count,
            "timestamp": "",
        })
        return resp
    except Exception as e:
        st.error(f"Option chain error: {e}")
        return {}


def parse_option_chain(chain_resp: dict, index: str) -> tuple[list, list, dict]:
    """
    Parse option chain response.
    Returns:
      expiries  — list of label strings e.g. ["19 MAY 26 (W)", ...]
      strikes   — sorted list of int strikes
      chain_df  — dict keyed by (expiry, strike, CE/PE) → row dict
    """
    if chain_resp.get("s") != "ok":
        return [], [], {}

    expiries_raw = chain_resp.get("data", {}).get("expiryData", [])
    options_raw  = chain_resp.get("data", {}).get("optionsChain", [])

    # Build expiry label list and update code cache
    expiries = []
    for e in expiries_raw:
        label  = e.get("expiry", "")
        expiry_date = e.get("date", "")
        if label:
            expiries.append(label)
            # Pre-populate code cache from date if available
            _cache_expiry_from_date(index, label, expiry_date, e.get("expiry_type", ""))

    strikes_set = set()
    chain_map = {}

    for row in options_raw:
        expiry = row.get("expiry", "")
        strike = int(float(row.get("strike_price", 0)))
        ot     = row.get("option_type", "")
        strikes_set.add(strike)
        chain_map[(expiry, strike, ot)] = {
            "ltp":       float(row.get("ltp", 0) or 0),
            "bid":       float(row.get("bid_price", 0) or 0),
            "ask":       float(row.get("ask_price", 0) or 0),
            "volume":    int(row.get("volume", 0) or 0),
            "oi":        int(row.get("oi", 0) or 0),
            "oi_change": int(row.get("change_in_oi", 0) or 0),
            "iv":        float(row.get("implied_volatility", 0) or 0),
            "delta":     float(row.get("delta", 0) or 0),
            "gamma":     float(row.get("gamma", 0) or 0),
            "theta":     float(row.get("theta", 0) or 0),
            "vega":      float(row.get("vega", 0) or 0),
            "prev_close": float(row.get("prev_close", 0) or 0),
        }

    return expiries, sorted(strikes_set), chain_map


def _cache_expiry_from_date(index: str, label: str, date_str: str, expiry_type: str):
    """
    Pre-populate expiry_code_cache using the date field from option chain.
    date_str format varies; we also use our direct parser as fallback.
    """
    # Our direct parser already handles this correctly; just run it to populate cache
    label_to_code(label, index)


# ─────────────────────────────────────────────────────
# HISTORICAL CANDLES
# ─────────────────────────────────────────────────────

RESOLUTION_MAP = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "1D": "1D"}

def fetch_candles(fyers, symbol: str, resolution: str = "5m",
                  date_from: str = "", date_to: str = "") -> pd.DataFrame:
    """
    Fetch OHLCV candles from Fyers.
    Returns DataFrame with columns: datetime, open, high, low, close, volume
    """
    if not date_from:
        date_from = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
    if not date_to:
        date_to = date_from

    res = RESOLUTION_MAP.get(resolution, "5")

    try:
        resp = fyers.history({
            "symbol":      symbol,
            "resolution":  res,
            "date_format": "1",
            "range_from":  date_from,
            "range_to":    date_to,
            "cont_flag":   "1",
        })
        if resp.get("s") != "ok":
            return pd.DataFrame()

        candles = resp.get("candles", [])
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
        return df[["datetime", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        st.error(f"Candle fetch error: {e}")
        return pd.DataFrame()
