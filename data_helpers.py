"""
data_helpers.py
───────────────
All sample-data generators live here.
To go live, replace get_option_price() and generate_spread_ohlcv()
with real API calls using dhan_client.py or angelone_client.py
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import math
import random

# ─── Safe optional import of live API client ─────────────────────────────────
# Won't crash if dhan_client or angelone_client is missing or not configured
try:
    from dhan_client import get_live_ltp as _dhan_ltp
    from dhan_client import get_live_spread_ohlcv as _dhan_spread
    DHAN_LIVE = True
except Exception:
    DHAN_LIVE = False

try:
    from angelone_client import get_live_ltp as _angel_ltp
    ANGEL_LIVE = True
except Exception:
    ANGEL_LIVE = False

# ─── Option universe ──────────────────────────────────────────────────────────
NIFTY_STRIKES   = list(range(21000, 24500, 50))
SENSEX_STRIKES  = list(range(72000, 88000, 500))
NIFTY_EXPIRIES  = ["10 Apr", "13 Apr", "17 Apr", "24 Apr", "01 May", "29 May", "26 Jun"]
SENSEX_EXPIRIES = ["11 Apr", "14 Apr", "22 Apr", "28 Apr", "05 May", "30 Jun", "31 Jul"]
NIFTY_ATM       = 22800
SENSEX_ATM      = 82500
NIFTY_SPOT      = 22820.0
SENSEX_SPOT     = 82540.0
RISK_FREE_RATE  = 0.065
TF_MAP          = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}


# ─── Black-Scholes helpers ────────────────────────────────────────────────────
def _days_to_expiry(expiry_str: str) -> float:
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    try:
        parts   = expiry_str.strip().split()
        day     = int(parts[0])
        mon     = months[parts[1]]
        year    = datetime.now().year
        exp_dt  = datetime(year, mon, day)
        if exp_dt < datetime.now():
            exp_dt = datetime(year + 1, mon, day)
        dte = (exp_dt - datetime.now()).days
        return max(dte, 1) / 365.0
    except Exception:
        return 30 / 365.0


def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


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


# ─── Sample price (fallback when no live API) ─────────────────────────────────
def _sample_price(index: str, strike: int, expiry: str, cp: str) -> float:
    spot  = NIFTY_SPOT if index == "NIFTY" else SENSEX_SPOT
    T     = _days_to_expiry(expiry)
    sigma = 0.14 + random.Random(f"{index}{strike}{expiry}{cp}").uniform(-0.03, 0.04)
    price = bs_price(spot, strike, T, RISK_FREE_RATE, sigma, cp)
    return round(max(0.5, price), 2)


# ─── Sample OHLCV (fallback when no live API) ─────────────────────────────────
def _sample_ohlcv(base_val: float, n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:
    np.random.seed(int(abs(base_val) * 100) % 9999)
    price = base_val if base_val != 0 else 25.0
    rows  = []
    now   = datetime.now()
    for i in range(n_bars, -1, -1):
        ts  = now - timedelta(minutes=i * tf_minutes)
        o   = price
        vol = abs(base_val) * 0.018 if abs(base_val) > 1 else 0.5
        c   = o + np.random.normal(0, vol)
        h   = max(o, c) + abs(np.random.normal(0, vol * 0.4))
        l   = min(o, c) - abs(np.random.normal(0, vol * 0.4))
        rows.append({"time": ts, "open": round(o,2), "high": round(h,2),
                     "low": round(l,2), "close": round(c,2)})
        price = c
    return pd.DataFrame(rows)


# ─── Main functions (called by all pages) ────────────────────────────────────

def get_option_price(index: str, strike: int, expiry: str, cp: str) -> float:
    """
    Returns LTP for a given option contract.
    Tries Dhan live API first, then AngelOne, then falls back to sample data.
    """
    if DHAN_LIVE:
        try:
            return _dhan_ltp(index, strike, expiry, cp)
        except Exception:
            pass
    if ANGEL_LIVE:
        try:
            return _angel_ltp(index, strike, expiry, cp)
        except Exception:
            pass
    # Fallback — sample data
    return _sample_price(index, strike, expiry, cp)


def generate_spread_ohlcv(base_val_or_legs, n_bars: int = 80,
                           tf_minutes: int = 1) -> pd.DataFrame:
    """
    Returns OHLCV DataFrame for the spread.
    - If live API available: fetches real candles per leg and combines them
    - Otherwise: generates sample data using base_val as seed
    """
    if DHAN_LIVE and isinstance(base_val_or_legs, list):
        tf_map = {1:"1", 5:"5", 15:"15", 60:"60", 375:"D"}
        try:
            return _dhan_spread(base_val_or_legs,
                                tf_map.get(tf_minutes, "1"))
        except Exception:
            pass
    # Fallback — sample data
    base_val = base_val_or_legs if isinstance(base_val_or_legs, (int, float)) else 25.0
    return _sample_ohlcv(base_val, n_bars, tf_minutes)


def get_iv_series(index: str, strike: int, expiry: str, cp: str,
                  n_bars: int = 60, tf_minutes: int = 5) -> pd.DataFrame:
    """Returns time-series of IV (%) for an option."""
    spot     = NIFTY_SPOT if index == "NIFTY" else SENSEX_SPOT
    T        = _days_to_expiry(expiry)
    base_iv  = 0.13 + random.Random(f"{index}{strike}{expiry}{cp}").uniform(0, 0.06)
    np.random.seed(hash(f"{index}{strike}{expiry}{cp}") % 9999)
    iv   = base_iv
    rows = []
    now  = datetime.now()
    for i in range(n_bars, -1, -1):
        ts  = now - timedelta(minutes=i * tf_minutes)
        iv += np.random.normal(0, 0.003)
        iv  = max(0.05, min(1.5, iv))
        rows.append({"time": ts, "iv_pct": round(iv * 100, 2)})
    return pd.DataFrame(rows)


def get_multiplier_series(sx_strike: int, sx_expiry: str,
                           n_strike: int, n_expiry: str,
                           n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:
    """SENSEX synthetic / NIFTY synthetic multiplier series."""
    np.random.seed(42)
    sx_synth  = SENSEX_ATM + 40.0
    n_synth   = NIFTY_ATM  + 18.0
    rows      = []
    now       = datetime.now()
    for i in range(n_bars, -1, -1):
        ts        = now - timedelta(minutes=i * tf_minutes)
        sx_synth += np.random.normal(0, 0.5)
        n_synth  += np.random.normal(0, 0.2)
        mult      = round(sx_synth / n_synth, 4) if n_synth != 0 else np.nan
        rows.append({"time": ts, "multiplier": mult,
                     "sx_synth": round(sx_synth, 2),
                     "n_synth":  round(n_synth,  2)})
    return pd.DataFrame(rows)
