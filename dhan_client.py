"""
dhan_client.py — Live data from Dhan API
"""

import streamlit as st
import pandas as pd
import math
from datetime import datetime, timedelta
import urllib.request
import io

try:
    from dhanhq import dhanhq
except ImportError:
    raise ImportError("Run: pip install dhanhq")


# ─── Auth ─────────────────────────────────────────────────────────────────────
def get_dhan_client():
    if "dhan_client" in st.session_state and st.session_state.dhan_client:
        return st.session_state.dhan_client
    client = dhanhq(
        st.secrets["DHAN_CLIENT_ID"],
        st.secrets["DHAN_ACCESS_TOKEN"]
    )
    st.session_state.dhan_client = client
    return client


# ─── Master script lookup ─────────────────────────────────────────────────────
def _load_master() -> pd.DataFrame:
    if "dhan_master" not in st.session_state:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        with urllib.request.urlopen(url, timeout=15) as r:
            content = r.read().decode("utf-8")
        st.session_state.dhan_master = pd.read_csv(io.StringIO(content))
    return st.session_state.dhan_master


def _expiry_fmt(expiry_str: str) -> str:
    """Convert '13 Apr' → '2025-04-13'"""
    months = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
              "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
    parts = expiry_str.strip().split()
    day   = parts[0].zfill(2)
    mon   = months.get(parts[1], "01")
    year  = str(datetime.now().year)
    return f"{year}-{mon}-{day}"


def get_security_id(index: str, strike: int, expiry_str: str, cp: str) -> str:
    """Look up Dhan security_id for an option contract."""

    print("DEBUG INPUT:", index, strike, expiry_str, cp)

    strike = int(float(strike))
    cp = cp.upper()
    expiry_fmt = _expiry_fmt(expiry_str)

    cache_key = f"dhan_token_{index}_{strike}_{expiry_fmt}_{cp}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    df = _load_master()

    exchange   = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    underlying = "NIFTY" if index == "NIFTY" else "SENSEX"
    opt_type   = cp   # ✅ FIXED

    mask = (
        (df["SEM_EXM_EXCH_ID"] == exchange) &
        (df["SEM_TRADING_SYMBOL"].str.contains(underlying, na=False)) &
        (df["SEM_STRIKE_PRICE"].astype(float) == float(strike)) &
        (df["SEM_OPTION_TYPE"] == opt_type) &
        (df["SEM_EXPIRY_DATE"].astype(str).str.contains(expiry_fmt))  # ✅ FIXED
    )

    result = df[mask]

    if result.empty:
        raise ValueError(
            f"No security found: {index} {strike} {expiry_str} {cp} "
            f"(looked for expiry={expiry_fmt}, exchange={exchange})"
        )

    sid = str(result.iloc[0]["SEM_SMST_SECURITY_ID"])
    st.session_state[cache_key] = sid
    return sid

# ─── Live LTP ─────────────────────────────────────────────────────────────────
def get_live_ltp(index: str, strike: int, expiry: str, cp: str) -> float:
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)
    resp        = dhan.get_market_feed_quote(
                      securities={exchange: [security_id]}
                  )
    if resp["status"] == "success":
        return float(resp["data"][exchange][security_id]["last_price"])
    raise ValueError(f"LTP failed: {resp}")


# ─── Live BID / ASK / LTP ─────────────────────────────────────────────────────
def get_live_bid_ask_ltp(index: str, strike: int,
                          expiry: str, cp: str) -> tuple:
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)
    resp        = dhan.get_market_feed_quote(
                      securities={exchange: [security_id]}
                  )
    if resp["status"] == "success":
        d   = resp["data"][exchange][security_id]
        ltp = float(d["last_price"])
        bid = float(d.get("best_bid_price", ltp * 0.998))
        ask = float(d.get("best_ask_price", ltp * 1.002))
        return round(bid, 2), round(ask, 2), round(ltp, 2)
    raise ValueError(f"Quote failed: {resp}")


# ─── Historical candles ───────────────────────────────────────────────────────
def _get_candles(index: str, strike: int, expiry: str,
                 cp: str, interval: str = "1") -> pd.DataFrame:
    dhan        = get_dhan_client()
    exchange    = "NSE_FO" if index == "NIFTY" else "BSE_FO"
    security_id = get_security_id(index, strike, expiry, cp)

    if interval == "D":
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        to_date   = datetime.now().strftime("%Y-%m-%d")
        resp = dhan.historical_daily_data(
            security_id   = security_id,
            exchange_segment = exchange,
            instrument_type  = "OPTIDX",
            expiry_code      = 0,
            from_date        = from_date,
            to_date          = to_date,
        )
    else:
        resp = dhan.intraday_minute_data(
            security_id      = security_id,
            exchange_segment = exchange,
            instrument_type  = "OPTIDX",
        )

    if resp["status"] != "success":
        raise ValueError(f"Candle fetch failed: {resp}")

    d  = resp["data"]
    df = pd.DataFrame({
        "time":   pd.to_datetime(d["timestamp"]),
        "open":   d["open"],
        "high":   d["high"],
        "low":    d["low"],
        "close":  d["close"],
        "volume": d.get("volume", [0] * len(d["open"])),
    })
    return df


# ─── Live spread OHLCV ────────────────────────────────────────────────────────
def get_live_spread_ohlcv(legs: list, interval: str = "1") -> pd.DataFrame:
    """Fetch candles per leg, combine into spread OHLCV."""
    spread_close = None
    base_df      = None

    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"],
                              leg["expiry"], leg["cp"], interval)
        price = df.set_index("time")["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price

        if spread_close is None:
            spread_close = price
            base_df      = df
        else:
            spread_close = spread_close.add(price, fill_value=0)

    out          = pd.DataFrame()
    out["time"]  = base_df["time"].values
    out["close"] = spread_close.values
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open", "close"]].max(axis=1)
    out["low"]   = out[["open", "close"]].min(axis=1)
    return out.reset_index(drop=True)


# ─── Live IV series ───────────────────────────────────────────────────────────
def get_iv_series_live(index: str, strike: int, expiry: str,
                        cp: str, tf_minutes: int = 5) -> pd.DataFrame:
    """
    Fetch historical LTPs for an option and compute IV per bar using B-S.
    """
    tf_map = {1:"1", 5:"5", 15:"15", 60:"60", 375:"D"}
    df     = _get_candles(index, strike, expiry, cp,
                           tf_map.get(tf_minutes, "5"))

    from data_helpers import bs_price, implied_volatility, _days_to_expiry, RISK_FREE_RATE
    spot = float(get_live_ltp(index,
                               strike,   # use ATM approx
                               expiry, cp))
    T    = _days_to_expiry(expiry)
    rows = []
    for _, row in df.iterrows():
        try:
            iv = implied_volatility(row["close"], spot, strike,
                                    T, RISK_FREE_RATE, cp)
            iv_pct = round(iv * 100, 2)
        except Exception:
            iv_pct = 0.0
        rows.append({"time": row["time"], "iv_pct": iv_pct})
    return pd.DataFrame(rows)


# ─── Live multiplier series ───────────────────────────────────────────────────
def get_multiplier_series_live(sx_strike: int, sx_expiry: str,
                                n_strike: int,  n_expiry: str,
                                interval: str = "1") -> pd.DataFrame:
    """
    SENSEX synthetic / NIFTY synthetic bar-by-bar.
    sx_synth = sx_strike + sx_CE - sx_PE
    n_synth  = n_strike  + n_CE  - n_PE
    multiplier = sx_synth / n_synth
    """
    # Fetch all 4 legs
    sx_ce_df = _get_candles("SENSEX", sx_strike, sx_expiry, "CE", interval)
    sx_pe_df = _get_candles("SENSEX", sx_strike, sx_expiry, "PE", interval)
    n_ce_df  = _get_candles("NIFTY",  n_strike,  n_expiry,  "CE", interval)
    n_pe_df  = _get_candles("NIFTY",  n_strike,  n_expiry,  "PE", interval)

    # Align on time index
    sx_ce = sx_ce_df.set_index("time")["close"]
    sx_pe = sx_pe_df.set_index("time")["close"]
    n_ce  = n_ce_df.set_index("time")["close"]
    n_pe  = n_pe_df.set_index("time")["close"]

    sx_synth   = sx_strike + sx_ce - sx_pe
    n_synth    = n_strike  + n_ce  - n_pe
    multiplier = (sx_synth / n_synth).round(4)

    df = pd.DataFrame({
        "time":       sx_synth.index,
        "multiplier": multiplier.values,
        "sx_synth":   sx_synth.values.round(2),
        "n_synth":    n_synth.values.round(2),
    }).reset_index(drop=True)
    return df
