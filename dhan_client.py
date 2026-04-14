"""
dhan_client.py — Live data from Dhan API
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import urllib.request
import io
from dhanhq import dhanhq


# ─── AUTH ─────────────────────────────────────────────────────────────────────
def get_dhan_client():
    if "dhan_client" in st.session_state:
        return st.session_state.dhan_client

    client = dhanhq(
        st.secrets["DHAN_CLIENT_ID"],
        st.secrets["DHAN_ACCESS_TOKEN"]
    )
    st.session_state.dhan_client = client
    return client


# ─── LOAD MASTER ──────────────────────────────────────────────────────────────
def _load_master() -> pd.DataFrame:
    if "dhan_master" not in st.session_state:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        with urllib.request.urlopen(url, timeout=15) as r:
            content = r.read().decode("utf-8")
        st.session_state.dhan_master = pd.read_csv(io.StringIO(content))
    return st.session_state.dhan_master


# ─── AUTO EXPIRY ──────────────────────────────────────────────────────────────
def get_next_expiry(index: str):
    today = datetime.now()

    if index == "NIFTY":
        target_day = 1  # Tuesday
    else:
        target_day = 3  # Thursday

    days_ahead = (target_day - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7

    expiry = today + timedelta(days=days_ahead)
    return expiry.strftime("%d %b")


# ─── EXPIRY FORMAT ────────────────────────────────────────────────────────────
def _expiry_fmt(expiry_str: str) -> str:
    expiry_str = str(expiry_str).strip()

    try:
        return datetime.strptime(expiry_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        pass

    try:
        year = datetime.now().year
        dt = datetime.strptime(f"{expiry_str} {year}", "%d %b %Y")
        return dt.strftime("%Y-%m-%d")
    except:
        pass

    try:
        dt = datetime.strptime(expiry_str, "%d %b %Y")
        return dt.strftime("%Y-%m-%d")
    except:
        pass

    return expiry_str


# ─── SECURITY ID LOOKUP ───────────────────────────────────────────────────────
def get_security_id(index: str, strike: int, expiry_str: str, cp: str) -> str:

    strike = int(float(strike))
    cp = cp.upper()
    expiry_fmt = _expiry_fmt(expiry_str)

    cache_key = f"dhan_token_{index}_{strike}_{expiry_fmt}_{cp}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    df = _load_master()

    exchange   = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    underlying = "NIFTY" if index == "NIFTY" else "SENSEX"

    mask = (
        (df["SEM_EXM_EXCH_ID"] == exchange) &
        (df["SEM_TRADING_SYMBOL"].str.contains(underlying, na=False)) &
        (df["SEM_STRIKE_PRICE"].astype(float) == float(strike)) &
        (df["SEM_OPTION_TYPE"] == cp) &
        (df["SEM_EXPIRY_DATE"].astype(str).str.contains(expiry_fmt))
    )

    result = df[mask]

    if result.empty:
        st.error(f"❌ No contract found: {index} {strike} {expiry_str} {cp}")
        st.stop()

    sid = str(result.iloc[0]["SEM_SMST_SECURITY_ID"])
    st.session_state[cache_key] = sid
    return sid


# ─── LIVE LTP ─────────────────────────────────────────────────────────────────
def get_live_ltp(index: str, strike: int, expiry: str, cp: str) -> float:
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    resp = dhan.get_market_feed_quote(
        securities={exchange: [security_id]}
    )

    if resp["status"] == "success":
        return float(resp["data"][exchange][security_id]["last_price"])

    st.error("❌ LTP fetch failed")
    st.stop()


# ─── LIVE BID / ASK / LTP ─────────────────────────────────────────────────────
def get_live_bid_ask_ltp(index: str, strike: int, expiry: str, cp: str):
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    resp = dhan.get_market_feed_quote(
        securities={exchange: [security_id]}
    )

    if resp["status"] == "success":
        d   = resp["data"][exchange][security_id]
        ltp = float(d["last_price"])
        bid = float(d.get("best_bid_price", ltp * 0.998))
        ask = float(d.get("best_ask_price", ltp * 1.002))
        return round(bid, 2), round(ask, 2), round(ltp, 2)

    st.error("❌ Quote fetch failed")
    st.stop()


# ─── CANDLES ──────────────────────────────────────────────────────────────────
def _get_candles(index, strike, expiry, cp, interval="1"):
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    if interval == "D":
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        to_date   = datetime.now().strftime("%Y-%m-%d")

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

    if resp["status"] != "success":
        st.error("❌ Candle fetch failed")
        st.stop()

    d = resp["data"]

    return pd.DataFrame({
        "time": pd.to_datetime(d["timestamp"]),
        "open": d["open"],
        "high": d["high"],
        "low": d["low"],
        "close": d["close"],
        "volume": d.get("volume", [0]*len(d["open"]))
    })


# ─── SPREAD OHLCV ─────────────────────────────────────────────────────────────
def get_live_spread_ohlcv(legs: list, interval: str = "1") -> pd.DataFrame:
    spread_close = None
    base_df = None

    for leg in legs:
        df = _get_candles(
            leg["index"], leg["strike"], leg["expiry"], leg["cp"], interval
        )
        price = df.set_index("time")["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price

        if spread_close is None:
            spread_close = price
            base_df = df
        else:
            spread_close = spread_close.add(price, fill_value=0)

    out = pd.DataFrame()
    out["time"] = base_df["time"].values
    out["close"] = spread_close.values
    out["open"] = out["close"].shift(1).fillna(out["close"])
    out["high"] = out[["open", "close"]].max(axis=1)
    out["low"] = out[["open", "close"]].min(axis=1)

    return out.reset_index(drop=True)
