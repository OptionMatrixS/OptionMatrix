"""
data_helpers.py — ALL LIVE DATA via Dhan API, no sample data
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import math
import streamlit as st
from dhan_client import (
    get_live_ltp,
    get_live_bid_ask_ltp,
    get_live_spread_ohlcv,
    get_iv_series_live,
    get_multiplier_series_live,
)

# ─── Option universe ──────────────────────────────────────────────────────────
NIFTY_STRIKES  = list(range(21000, 24500, 50))
SENSEX_STRIKES = list(range(72000, 88000, 500))
NIFTY_EXPIRIES  = ["10 Apr", "13 Apr", "17 Apr", "24 Apr", "01 May", "29 May", "26 Jun"]
SENSEX_EXPIRIES = ["11 Apr", "14 Apr", "22 Apr", "28 Apr", "05 May", "30 Jun", "31 Jul"]
NIFTY_ATM      = 22800
SENSEX_ATM     = 82500
RISK_FREE_RATE = 0.065
TF_MAP         = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}


# ─── Black-Scholes (used for IV calculator) ───────────────────────────────────
def _days_to_expiry(expiry_str: str) -> float:
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    try:
        parts  = expiry_str.strip().split()
        day    = int(parts[0])
        mon    = months[parts[1]]
        year   = datetime.now().year
        exp_dt = datetime(year, mon, day)
        if exp_dt < datetime.now():
            exp_dt = datetime(year + 1, mon, day)
        return max((exp_dt - datetime.now()).days, 1) / 365.0
    except Exception:
        return 30 / 365.0


def _norm_cdf(x):
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


# ─── Main functions called by all pages ──────────────────────────────────────

def get_option_price(index: str, strike: int, expiry: str, cp: str) -> float:
    """Live LTP from Dhan."""
    return get_live_ltp(index, strike, expiry, cp)


def get_spread_bid_ask_ltp(legs: list, strikes_per_leg: list) -> tuple:
    """
    Live spread BID / ASK / LTP — sums across all legs.
    Used by safety_calculator.py
    """
    bid_total = ask_total = ltp_total = 0.0
    for leg, strike in zip(legs, strikes_per_leg):
        bid, ask, ltp = get_live_bid_ask_ltp(
            leg["index"], strike, leg["expiry"], leg["cp"]
        )
        sign = 1 if leg["bs"] == "Buy" else -1
        bid_total += sign * bid * leg["ratio"]
        ask_total += sign * ask * leg["ratio"]
        ltp_total += sign * ltp * leg["ratio"]
    return round(bid_total, 2), round(ask_total, 2), round(ltp_total, 2)


def generate_spread_ohlcv(legs, tf_minutes: int = 1) -> pd.DataFrame:
    """
    Live spread OHLCV from Dhan candles.
    legs = list of dicts: {index, strike, expiry, cp, bs, ratio}
    """
    tf_map = {1: "1", 5: "5", 15: "15", 60: "60", 375: "D"}
    return get_live_spread_ohlcv(legs, tf_map.get(tf_minutes, "1"))


def get_iv_series(index: str, strike: int, expiry: str, cp: str,
                  n_bars: int = 60, tf_minutes: int = 5) -> pd.DataFrame:
    """
    Live IV time-series — fetches historical LTPs and computes IV per bar.
    """
    return get_iv_series_live(index, strike, expiry, cp, tf_minutes)


def get_multiplier_series(sx_strike: int, sx_expiry: str,
                           n_strike: int, n_expiry: str,
                           n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:
    """
    Live SENSEX/NIFTY synthetic multiplier from Dhan candles.
    """
    tf_map = {1: "1", 5: "5", 15: "15", 60: "60", 375: "D"}
    return get_multiplier_series_live(
        sx_strike, sx_expiry, n_strike, n_expiry,
        tf_map.get(tf_minutes, "1")
    )
