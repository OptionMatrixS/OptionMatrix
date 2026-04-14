"""
dhan_client.py — All live data from Dhan API
Credentials read from st.secrets: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN
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
    raise ImportError("pip install dhanhq")

RISK_FREE_RATE = 0.065

# ─── Auth ─────────────────────────────────────────────────────────────────────
def get_dhan_client():
    if "dhan_client" in st.session_state and st.session_state.dhan_client:
        return st.session_state.dhan_client
    client = dhanhq(st.secrets["DHAN_CLIENT_ID"], st.secrets["DHAN_ACCESS_TOKEN"])
    st.session_state.dhan_client = client
    return client

# ─── Master CSV ───────────────────────────────────────────────────────────────
def _load_master() -> pd.DataFrame:
    if "dhan_master" not in st.session_state:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        with urllib.request.urlopen(url, timeout=15) as r:
            content = r.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(content))
        df = df[df["SEM_INSTRUMENT_NAME"].isin(["OPTIDX", "OPTSTK"])]
        df["SEM_EXPIRY_DATE"]   = pd.to_datetime(df["SEM_EXPIRY_DATE"], errors="coerce")
        df["SEM_STRIKE_PRICE"]  = pd.to_numeric(df["SEM_STRIKE_PRICE"], errors="coerce")
        st.session_state.dhan_master = df
    return st.session_state.dhan_master

def _parse_expiry(expiry_str: str) -> pd.Timestamp:
    try:
        parts = expiry_str.strip().split()
        if len(parts) == 2:
            expiry_str = f"{parts[0]} {parts[1]} {datetime.now().year}"
        return pd.Timestamp(expiry_str)
    except Exception:
        return pd.Timestamp(datetime.now().date())

def _underlying(index: str) -> str:
    return {"NIFTY": "NIFTY", "SENSEX": "SENSEX", "BANKNIFTY": "BANKNIFTY"}[index]

def _exchange(index: str) -> str:
    return "BSE_FO" if index == "SENSEX" else "NSE_FO"

# ─── Live expiries & strikes ──────────────────────────────────────────────────
def get_expiries(index: str) -> list:
    df    = _load_master()
    exch  = _exchange(index)
    uname = _underlying(index)
    mask  = (df["SEM_EXM_EXCH_ID"] == exch) &             (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False))
    today  = pd.Timestamp(datetime.now().date())
    dates  = sorted([e for e in df[mask]["SEM_EXPIRY_DATE"].dropna().unique() if e >= today])
    if not dates:
        raise ValueError(f"No expiries found for {index} ({exch}). Check Dhan master CSV.")
    # Use %-d on Linux; on Windows use %#d
    try:
        return [e.strftime("%-d %b") for e in dates[:12]]
    except ValueError:
        return [e.strftime("%#d %b") for e in dates[:12]]

def get_strikes(index: str, expiry_str: str) -> list:
    try:
        df     = _load_master()
        exch   = _exchange(index)
        uname  = _underlying(index)
        exp_dt = _parse_expiry(expiry_str)
        mask   = (df["SEM_EXM_EXCH_ID"] == exch) & \
                 (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False)) & \
                 (df["SEM_EXPIRY_DATE"]  == exp_dt)
        strikes = sorted(df[mask]["SEM_STRIKE_PRICE"].dropna().unique().tolist())
        return [int(s) for s in strikes]
    except Exception:
        return []

# ─── Security ID ──────────────────────────────────────────────────────────────
def get_security_id(index: str, strike: int, expiry_str: str, cp: str) -> str:
    cache_key = f"sec_{index}_{strike}_{expiry_str}_{cp}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    df       = _load_master()
    exch     = _exchange(index)
    uname    = _underlying(index)
    opt_type = "CALL" if cp == "CE" else "PUT"
    exp_dt   = _parse_expiry(expiry_str)
    mask = (
        (df["SEM_EXM_EXCH_ID"] == exch) &
        (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False)) &
        (df["SEM_STRIKE_PRICE"] == float(strike)) &
        (df["SEM_EXPIRY_DATE"]  == exp_dt) &
        (df["SEM_OPTION_TYPE"]  == opt_type)
    )
    result = df[mask]
    if result.empty:
        exp_dt2 = pd.Timestamp(exp_dt.year + 1, exp_dt.month, exp_dt.day)
        mask2   = mask.copy()
        result  = df[
            (df["SEM_EXM_EXCH_ID"] == exch) &
            (df["SEM_TRADING_SYMBOL"].str.contains(uname, na=False)) &
            (df["SEM_STRIKE_PRICE"] == float(strike)) &
            (df["SEM_EXPIRY_DATE"]  == exp_dt2) &
            (df["SEM_OPTION_TYPE"]  == opt_type)
        ]
    if result.empty:
        raise ValueError(f"No security: {index} {strike} {expiry_str} {cp}")
    sid = str(result.iloc[0]["SEM_SMST_SECURITY_ID"])
    st.session_state[cache_key] = sid
    return sid

# ─── Live quote ───────────────────────────────────────────────────────────────
def get_live_quote(index: str, strike: int, expiry: str, cp: str) -> dict:
    """Returns dict with bid, ask, ltp, prev_close"""
    dhan = get_dhan_client()
    exch = _exchange(index)
    sid  = get_security_id(index, strike, expiry, cp)
    resp = dhan.get_market_feed_quote(securities={exch: [sid]})
    if resp["status"] == "success":
        d = resp["data"][exch][sid]
        ltp = float(d.get("last_price", 0))
        return {
            "ltp":        ltp,
            "bid":        float(d.get("best_bid_price", ltp * 0.998)),
            "ask":        float(d.get("best_ask_price", ltp * 1.002)),
            "prev_close": float(d.get("previous_close_price", 0)),
            "high":       float(d.get("high_price", ltp)),
            "low":        float(d.get("low_price",  ltp)),
        }
    raise ValueError(f"Quote failed: {resp}")

def get_live_ltp(index, strike, expiry, cp) -> float:
    return get_live_quote(index, strike, expiry, cp)["ltp"]

def get_live_bid_ask_ltp(index, strike, expiry, cp) -> tuple:
    q = get_live_quote(index, strike, expiry, cp)
    return q["bid"], q["ask"], q["ltp"]

# ─── Black-Scholes Greeks ─────────────────────────────────────────────────────
def _norm_cdf(x):
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0

def _norm_pdf(x):
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

def bs_price(S, K, T, r, sigma, cp):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "CE" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if cp == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

def implied_volatility(market_price, S, K, T, r, cp, tol=1e-5, max_iter=200):
    if market_price <= 0:
        return 0.0
    low, high = 0.001, 5.0
    for _ in range(max_iter):
        mid   = (low + high) / 2
        price = bs_price(S, K, T, r, mid, cp)
        if abs(price - market_price) < tol:
            return mid
        if price < market_price:
            low = mid
        else:
            high = mid
    return mid

def bs_greeks(S, K, T, r, sigma, cp) -> dict:
    """Returns delta, gamma, vega, theta, iv"""
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0, "iv": sigma}
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    pdf_d1 = _norm_pdf(d1)
    gamma  = pdf_d1 / (S * sigma * math.sqrt(T))
    vega   = S * pdf_d1 * math.sqrt(T) / 100  # per 1% vol move
    if cp == "CE":
        delta = _norm_cdf(d1)
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(S * pdf_d1 * sigma) / (2 * math.sqrt(T))
                 + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365
    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "vega": round(vega, 4),   "theta": round(theta, 4),
            "iv":   round(sigma * 100, 2)}

def get_spread_greeks(legs: list, spot_prices: dict) -> dict:
    """
    Calculate net greeks for a spread across all legs.
    spot_prices: {index: spot_price}  e.g. {"NIFTY": 22800}
    """
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "iv": []}
    for leg in legs:
        try:
            S      = spot_prices.get(leg["index"], 22800)
            K      = leg["strike"]
            T      = _days_to_expiry(leg["expiry"])
            ltp    = get_live_ltp(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
            sigma  = implied_volatility(ltp, S, K, T, RISK_FREE_RATE, leg["cp"])
            g      = bs_greeks(S, K, T, RISK_FREE_RATE, sigma, leg["cp"])
            sign   = 1 if leg["bs"] == "Buy" else -1
            ratio  = leg["ratio"]
            net["delta"] += sign * ratio * g["delta"]
            net["gamma"] += sign * ratio * g["gamma"]
            net["vega"]  += sign * ratio * g["vega"]
            net["theta"] += sign * ratio * g["theta"]
            net["iv"].append(g["iv"])
        except Exception:
            pass
    net["delta"] = round(net["delta"], 4)
    net["gamma"] = round(net["gamma"], 6)
    net["vega"]  = round(net["vega"],  4)
    net["theta"] = round(net["theta"], 4)
    net["net_iv"] = round(sum(net["iv"]) / len(net["iv"]), 2) if net["iv"] else 0
    del net["iv"]
    return net

# ─── Live spot price ──────────────────────────────────────────────────────────
def get_spot_price(index: str) -> float:
    """Get underlying spot price from Dhan."""
    try:
        df    = _load_master()
        exch  = _exchange(index)
        uname = _underlying(index)
        # get ATM strike from nearest expiry CE to estimate spot
        expiries = get_expiries(index)
        if not expiries:
            return 22800 if index == "NIFTY" else (82500 if index == "SENSEX" else 48000)
        strikes = get_strikes(index, expiries[0])
        if not strikes:
            return 22800
        mid_strike = strikes[len(strikes) // 2]
        ce_ltp = get_live_ltp(index, mid_strike, expiries[0], "CE")
        pe_ltp = get_live_ltp(index, mid_strike, expiries[0], "PE")
        return round(mid_strike + ce_ltp - pe_ltp, 2)
    except Exception:
        return 22800 if index == "NIFTY" else (82500 if index == "SENSEX" else 48000)

# ─── Historical candles ───────────────────────────────────────────────────────
def _get_candles(index, strike, expiry, cp, interval="1") -> pd.DataFrame:
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
            security_id=sid, exchange_segment=exch, instrument_type="OPTIDX")
    if resp["status"] != "success":
        raise ValueError(f"Candle fetch failed: {resp}")
    d = resp["data"]
    return pd.DataFrame({
        "time":   pd.to_datetime(d["timestamp"]),
        "open":   d["open"], "high": d["high"],
        "low":    d["low"],  "close": d["close"],
    })

def get_live_spread_ohlcv(legs, interval="1") -> pd.DataFrame:
    spread_close = None
    base_df      = None
    for leg in legs:
        df    = _get_candles(leg["index"], leg["strike"], leg["expiry"], leg["cp"], interval)
        price = df.set_index("time")["close"] * leg["ratio"]
        price = price if leg["bs"] == "Buy" else -price
        if spread_close is None:
            spread_close, base_df = price, df
        else:
            spread_close = spread_close.add(price, fill_value=0)
    out = pd.DataFrame()
    out["time"]  = base_df["time"].values
    out["close"] = spread_close.values
    out["open"]  = out["close"].shift(1).fillna(out["close"])
    out["high"]  = out[["open","close"]].max(axis=1)
    out["low"]   = out[["open","close"]].min(axis=1)
    return out.reset_index(drop=True)

def get_iv_series_live(index, strike, expiry, cp, tf_minutes=5) -> pd.DataFrame:
    tf_map = {1:"1",5:"5",15:"15",60:"60",375:"D"}
    df     = _get_candles(index, strike, expiry, cp, tf_map.get(tf_minutes,"5"))
    spot   = get_spot_price(index)
    T      = _days_to_expiry(expiry)
    rows   = []
    for _, row in df.iterrows():
        try:
            iv = implied_volatility(row["close"], spot, strike, T, RISK_FREE_RATE, cp)
            iv_pct = round(iv * 100, 2)
        except Exception:
            iv_pct = 0.0
        rows.append({"time": row["time"], "iv_pct": iv_pct})
    return pd.DataFrame(rows)

def get_multiplier_series_live(sx_strike, sx_expiry, n_strike, n_expiry, interval="1") -> pd.DataFrame:
    sx_ce = _get_candles("SENSEX", sx_strike, sx_expiry, "CE", interval).set_index("time")["close"]
    sx_pe = _get_candles("SENSEX", sx_strike, sx_expiry, "PE", interval).set_index("time")["close"]
    n_ce  = _get_candles("NIFTY",  n_strike,  n_expiry,  "CE", interval).set_index("time")["close"]
    n_pe  = _get_candles("NIFTY",  n_strike,  n_expiry,  "PE", interval).set_index("time")["close"]
    sx_synth   = sx_strike + sx_ce - sx_pe
    n_synth    = n_strike  + n_ce  - n_pe
    multiplier = (sx_synth / n_synth).round(4)
    return pd.DataFrame({
        "time": sx_synth.index, "multiplier": multiplier.values,
        "sx_synth": sx_synth.values.round(2), "n_synth": n_synth.values.round(2),
    }).reset_index(drop=True)
