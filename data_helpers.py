"""
data_helpers.py
───────────────
All sample-data generators live here.
To go live, replace the functions marked  # ← REPLACE WITH ANGELONE API
with real API calls. The rest of the app stays unchanged.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import math
import random

# ─── Option universe ──────────────────────────────────────────────────────────
NIFTY_STRIKES   = list(range(21000, 24500, 50))
SENSEX_STRIKES  = list(range(72000, 88000, 500))
NIFTY_EXPIRIES  = ["10 Apr", "13 Apr", "17 Apr", "24 Apr", "01 May", "29 May", "26 Jun"]
SENSEX_EXPIRIES = ["11 Apr", "14 Apr", "22 Apr", "28 Apr", "05 May", "30 Jun", "31 Jul"]
NIFTY_ATM       = 22800
SENSEX_ATM      = 82500
NIFTY_SPOT      = 22820.0
SENSEX_SPOT     = 82540.0
RISK_FREE_RATE  = 0.065   # 6.5% RBI repo
TF_MAP          = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}


# ─── Black-Scholes helpers ────────────────────────────────────────────────────
def _days_to_expiry(expiry_str: str) -> float:
    """Parse 'DD Mon' expiry string → years to expiry."""
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    try:
        parts = expiry_str.strip().split()
        day = int(parts[0])
        mon = months[parts[1]]
        year = datetime.now().year
        exp_dt = datetime(year, mon, day)
        if exp_dt < datetime.now():
            exp_dt = datetime(year + 1, mon, day)
        dte = (exp_dt - datetime.now()).days
        return max(dte, 1) / 365.0
    except Exception:
        return 30 / 365.0


def _norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2))) / 2.0


def bs_price(S: float, K: float, T: float, r: float, sigma: float, cp: str) -> float:
    """Black-Scholes option price."""
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "CE" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if cp == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_volatility(market_price: float, S: float, K: float, T: float,
                        r: float, cp: str, tol: float = 1e-5, max_iter: int = 200) -> float:
    """Bisection solver for IV."""
    low, high = 0.001, 5.0
    for _ in range(max_iter):
        mid = (low + high) / 2
        price = bs_price(S, K, T, r, mid, cp)
        if abs(price - market_price) < tol:
            return mid
        if price < market_price:
            low = mid
        else:
            high = mid
    return mid


# ─── Option price (sample) ────────────────────────────────────────────────────
def get_option_price(index: str, strike: int, expiry: str, cp: str) -> float:   # ← REPLACE WITH ANGELONE API
    """
    Returns LTP for a given contract.
    AngelOne: use getOptionChainData or MarketFeed WebSocket.
    """
    atm = NIFTY_ATM if index == "NIFTY" else SENSEX_ATM
    spot = NIFTY_SPOT if index == "NIFTY" else SENSEX_SPOT
    T = _days_to_expiry(expiry)
    sigma = 0.14 + random.Random(f"{index}{strike}{expiry}{cp}").uniform(-0.03, 0.04)
    price = bs_price(spot, strike, T, RISK_FREE_RATE, sigma, cp)
    return round(max(0.5, price), 2)


# ─── OHLCV for spread chart ───────────────────────────────────────────────────
def generate_spread_ohlcv(base_val: float, n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:  # ← REPLACE WITH ANGELONE API
    """
    Sample OHLCV for the spread series.
    Live: compute spread from per-leg candles fetched via AngelOne historical API.
    """
    np.random.seed(int(abs(base_val) * 100) % 9999)
    price = base_val if base_val != 0 else 25.0
    rows = []
    now = datetime.now()
    for i in range(n_bars, -1, -1):
        ts = now - timedelta(minutes=i * tf_minutes)
        o = price
        vol = abs(base_val) * 0.018 if abs(base_val) > 1 else 0.5
        c = o + np.random.normal(0, vol)
        h = max(o, c) + abs(np.random.normal(0, vol * 0.4))
        l = min(o, c) - abs(np.random.normal(0, vol * 0.4))
        rows.append({"time": ts, "open": round(o, 2), "high": round(h, 2),
                     "low": round(l, 2), "close": round(c, 2)})
        price = c
    return pd.DataFrame(rows)


# ─── IV time series for a strike ─────────────────────────────────────────────
def get_iv_series(index: str, strike: int, expiry: str, cp: str,
                  n_bars: int = 60, tf_minutes: int = 5) -> pd.DataFrame:  # ← REPLACE WITH ANGELONE API
    """
    Returns time-series of IV (%) for an option.
    Live: fetch historical LTPs, compute IV bar-by-bar using bs solver above.
    """
    spot = NIFTY_SPOT if index == "NIFTY" else SENSEX_SPOT
    T = _days_to_expiry(expiry)
    base_iv = 0.13 + random.Random(f"{index}{strike}{expiry}{cp}").uniform(0, 0.06)
    np.random.seed(hash(f"{index}{strike}{expiry}{cp}") % 9999)
    iv = base_iv
    rows = []
    now = datetime.now()
    for i in range(n_bars, -1, -1):
        ts = now - timedelta(minutes=i * tf_minutes)
        iv += np.random.normal(0, 0.003)
        iv = max(0.05, min(1.5, iv))
        rows.append({"time": ts, "iv_pct": round(iv * 100, 2)})
    return pd.DataFrame(rows)


# ─── Synthetic spot (put-call parity) ────────────────────────────────────────
def synthetic_spot(index: str, strike: int, expiry: str) -> float:  # ← REPLACE WITH ANGELONE API
    """Synthetic = Strike + CE - PE  (put-call parity)."""
    ce = get_option_price(index, strike, expiry, "CE")
    pe = get_option_price(index, strike, expiry, "PE")
    return round(strike + ce - pe, 2)


# ─── Multiplier series ────────────────────────────────────────────────────────
def get_multiplier_series(sx_strike: int, sx_expiry: str,
                           n_strike: int, n_expiry: str,
                           n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:  # ← REPLACE WITH ANGELONE API
    """
    SENSEX synthetic / NIFTY synthetic  (replicates the Pine Script logic).
    Live: fetch both synthetic series from AngelOne, divide bar-by-bar.
    """
    np.random.seed(42)
    sx_synth = SENSEX_ATM + 40.0
    n_synth  = NIFTY_ATM  + 18.0
    mult_base = round(sx_synth / n_synth, 4)

    rows = []
    now = datetime.now()
    for i in range(n_bars, -1, -1):
        ts = now - timedelta(minutes=i * tf_minutes)
        sx_synth += np.random.normal(0, 0.5)
        n_synth  += np.random.normal(0, 0.2)
        mult = round(sx_synth / n_synth, 4) if n_synth != 0 else np.nan
        rows.append({"time": ts, "multiplier": mult,
                     "sx_synth": round(sx_synth, 2), "n_synth": round(n_synth, 2)})
    return pd.DataFrame(rows)
