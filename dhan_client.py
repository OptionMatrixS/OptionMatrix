"""
dhan_client.py
──────────────
Dhan API integration for live options data.
Replaces angelone_client.py functions.

SETUP:
1. pip install dhanhq
2. Add to .streamlit/secrets.toml:
   DHAN_CLIENT_ID    = "your_client_id"
   DHAN_ACCESS_TOKEN = "your_access_token"
3. In data_helpers.py replace get_option_price() with get_live_ltp()
   and generate_spread_ohlcv() with get_live_spread_ohlcv()
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

try:
    from dhanhq import dhanhq
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False


# ─── Dhan exchange + segment constants ───────────────────────────────────────
# Dhan uses numeric segment IDs
NSE_FO  = "NSE_FO"   # Nifty options
BSE_FO  = "BSE_FO"   # Sensex options

# Dhan instrument type
CALL = "CALL"
PUT  = "PUT"


# ─── Auth ─────────────────────────────────────────────────────────────────────
def get_dhan_client():
    """
    Returns authenticated Dhan client.
    Cached in session state so re-runs don't re-authenticate.
    """
    if not DHAN_AVAILABLE:
        raise ImportError("Run: pip install dhanhq")

    if "dhan_client" in st.session_state and st.session_state.dhan_client:
        return st.session_state.dhan_client

    client_id    = st.secrets["DHAN_CLIENT_ID"]
    access_token = st.secrets["DHAN_ACCESS_TOKEN"]

    client = dhanhq(client_id, access_token)
    st.session_state.dhan_client = client
    return client


# ─── Symbol lookup ────────────────────────────────────────────────────────────
def get_security_id(index: str, strike: int, expiry_str: str, cp: str) -> str:
    """
    Look up Dhan security_id for an option contract.
    Dhan uses a master CSV file for symbol lookup.

    Steps:
    1. Download master CSV once
    2. Filter by index, strike, expiry, call/put
    3. Return security_id

    Master CSV URL:
    https://images.dhan.co/api-data/api-scrip-master.csv
    """
    import urllib.request
    import io

    # Download master CSV once per session
    if "dhan_scripts" not in st.session_state:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        with urllib.request.urlopen(url, timeout=10) as r:
            content = r.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(content))
        st.session_state.dhan_scripts = df

    df = st.session_state.dhan_scripts

    # Parse expiry — convert "13 Apr" → "2025-04-13"
    months = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
              "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
    parts      = expiry_str.strip().split()
    day        = parts[0].zfill(2)
    mon        = months.get(parts[1], "01")
    year       = str(datetime.now().year)
    expiry_fmt = f"{year}-{mon}-{day}"

    # Map index to Dhan underlying symbol
    underlying = "NIFTY" if index == "NIFTY" else "SENSEX"
    exchange   = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    opt_type   = "CALL" if cp == "CE" else "PUT"

    # Filter master CSV
    mask = (
        (df["SEM_EXM_EXCH_ID"]    == exchange) &
        (df["SEM_TRADING_SYMBOL"].str.contains(underlying, na=False)) &
        (df["SEM_STRIKE_PRICE"]   == float(strike)) &
        (df["SEM_EXPIRY_DATE"]    == expiry_fmt) &
        (df["SEM_OPTION_TYPE"]    == opt_type)
    )
    result = df[mask]

    if result.empty:
        raise ValueError(
            f"Security ID not found for {index} {strike} {expiry_str} {cp}. "
            f"Check expiry format or strike."
        )
    return str(result.iloc[0]["SEM_SMST_SECURITY_ID"])


# ─── Live LTP ─────────────────────────────────────────────────────────────────
def get_live_ltp(index: str, strike: int, expiry: str, cp: str) -> float:
    """
    Fetch live LTP for one option contract from Dhan.
    Use this to replace get_option_price() in data_helpers.py
    """
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    resp = dhan.get_market_feed_quote(
        securities={exchange: [security_id]}
    )

    if resp["status"] == "success":
        data = resp["data"][exchange][security_id]
        return float(data["last_price"])

    raise ValueError(f"LTP fetch failed: {resp}")


# ─── Live BID / ASK / LTP ─────────────────────────────────────────────────────
def get_live_bid_ask_ltp(index: str, strike: int, expiry: str, cp: str) -> tuple:
    """
    Returns (bid, ask, ltp) for one option contract.
    Use this in safety_calculator.py for real BID/ASK values.
    """
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    resp = dhan.get_market_feed_quote(
        securities={exchange: [security_id]}
    )

    if resp["status"] == "success":
        data = resp["data"][exchange][security_id]
        bid  = float(data.get("best_bid_price", data["last_price"] * 0.998))
        ask  = float(data.get("best_ask_price", data["last_price"] * 1.002))
        ltp  = float(data["last_price"])
        return round(bid, 2), round(ask, 2), round(ltp, 2)

    raise ValueError(f"Quote fetch failed: {resp}")


# ─── Historical OHLCV ─────────────────────────────────────────────────────────
def get_historical_candles(index: str, strike: int, expiry: str, cp: str,
                            interval: str = "1", days_back: int = 1) -> pd.DataFrame:
    """
    Fetch historical OHLCV candles for an option from Dhan.

    interval options:
      "1"   = 1 minute
      "5"   = 5 minutes
      "15"  = 15 minutes
      "25"  = 25 minutes
      "60"  = 1 hour
      "D"   = 1 day

    Returns DataFrame: time, open, high, low, close, volume
    """
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_date   = datetime.now().strftime("%Y-%m-%d")

    if interval == "D":
        resp = dhan.historical_daily_data(
            security_id=security_id,
            exchange_segment=exchange,
            instrument_type="OPTIDX",
            expiry_code=0,
            from_date=from_date,
            to_date=to_date,
        )
    else:
        resp = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment=exchange,
            instrument_type="OPTIDX",
        )

    if resp["status"] == "success":
        data = resp["data"]
        df = pd.DataFrame({
            "time":   pd.to_datetime(data["timestamp"]),
            "open":   data["open"],
            "high":   data["high"],
            "low":    data["low"],
            "close":  data["close"],
            "volume": data.get("volume", [0] * len(data["open"])),
        })
        return df

    raise ValueError(f"Candle fetch failed: {resp}")


# ─── Live Spread OHLCV ────────────────────────────────────────────────────────
def get_live_spread_ohlcv(legs: list, interval: str = "1") -> pd.DataFrame:
    """
    Compute spread OHLCV by fetching individual leg candles and combining.
    legs = list of dicts: {index, strike, expiry, cp, bs, ratio}

    Use this to replace generate_spread_ohlcv() in data_helpers.py
    """
    spread_close = None
    base_times   = None

    for leg in legs:
        df    = get_historical_candles(leg["index"], leg["strike"],
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
    out["high"]  = out[["open", "close"]].max(axis=1)
    out["low"]   = out[["open", "close"]].min(axis=1)
    return out


# ─── How to wire into data_helpers.py ────────────────────────────────────────
"""
STEP 1 — Add to top of data_helpers.py:
    from dhan_client import get_live_ltp, get_live_spread_ohlcv

STEP 2 — Replace get_option_price():
    def get_option_price(index, strike, expiry, cp):
        try:
            return get_live_ltp(index, strike, expiry, cp)
        except Exception as e:
            # fallback to sample data if API fails
            return _sample_price(index, strike, expiry, cp)

STEP 3 — Replace generate_spread_ohlcv():
    def generate_spread_ohlcv(legs, tf_minutes=1):
        tf_map = {1:"1", 5:"5", 15:"15", 60:"60", 375:"D"}
        try:
            return get_live_spread_ohlcv(legs, tf_map.get(tf_minutes, "1"))
        except Exception as e:
            return _sample_ohlcv(25, 80, tf_minutes)

STEP 4 — For Safety Calculator real BID/ASK:
    In safety_calculator.py replace _spread_price() internals:
    from dhan_client import get_live_bid_ask_ltp

    def _spread_price(legs, strikes_per_leg):
        bid_total = ask_total = ltp_total = 0.0
        for leg, strike in zip(legs, strikes_per_leg):
            bid, ask, ltp = get_live_bid_ask_ltp(
                leg["index"], strike, leg["expiry"], leg["cp"]
            )
            sign = 1 if leg["bs"] == "Buy" else -1
            bid_total += sign * bid  * leg["ratio"]
            ask_total += sign * ask  * leg["ratio"]
            ltp_total += sign * ltp  * leg["ratio"]
        return round(bid_total,2), round(ask_total,2), round(ltp_total,2)
"""
