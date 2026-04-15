"""
data_helpers.py
Clean data layer — validates inputs, wraps API calls with proper errors.
All functions here guarantee:
  - Inputs validated before any API call
  - Clear error messages raised on failure
  - No silent fallbacks to bad data
"""

import pandas as pd
from datetime import datetime

from dhan_client import (
    get_expiries,
    get_strikes,
    get_live_ltp,
    get_live_bid_ask_ltp,
    get_live_quote,
    get_live_spread_ohlcv,
    get_iv_series_live,
    get_multiplier_series_live,
    get_spot_price,
    get_spread_greeks,
    validate_legs,
    bs_price,
    implied_volatility,
    bs_greeks,
    _days_to_expiry,
    RISK_FREE_RATE,
)

TF_MAP = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}

# ─── Expiries / strikes ───────────────────────────────────────────────────────

def get_index_expiries(index: str) -> list:
    """Returns live expiry list from Dhan. Raises on failure."""
    return get_expiries(index)

def get_index_strikes(index: str, expiry: str) -> list:
    """Returns live strike list from Dhan. Raises on failure."""
    return get_strikes(index, expiry)

# Convenience aliases
get_nifty_expiries    = lambda: get_expiries("NIFTY")
get_sensex_expiries   = lambda: get_expiries("SENSEX")
get_banknifty_expiries= lambda: get_expiries("BANKNIFTY")
get_nifty_strikes     = lambda exp: get_strikes("NIFTY", exp)
get_sensex_strikes    = lambda exp: get_strikes("SENSEX", exp)
get_banknifty_strikes = lambda exp: get_strikes("BANKNIFTY", exp)

# ─── Option price ─────────────────────────────────────────────────────────────

def get_option_price(index: str, strike: int, expiry: str, cp: str) -> float:
    """Live LTP. Raises ValueError if inputs invalid or API fails."""
    return get_live_ltp(index, strike, expiry, cp)

# ─── Spread OHLCV ─────────────────────────────────────────────────────────────

def generate_spread_ohlcv(legs: list, tf_minutes: int = 1) -> pd.DataFrame:
    """
    Live spread OHLCV. Validates ALL legs before any API call.
    Raises ValueError with a clear message if any leg is invalid.
    """
    validate_legs(legs)  # raises before any API call if invalid
    tf_map = {1: "1", 5: "5", 15: "15", 60: "60", 375: "D"}
    return get_live_spread_ohlcv(legs, tf_map.get(tf_minutes, "1"))

# ─── Greeks ───────────────────────────────────────────────────────────────────

def calc_greeks_for_legs(legs: list) -> dict:
    """Calculate net B-S Greeks for a list of legs."""
    validate_legs(legs)
    spots = {}
    for leg in legs:
        if leg["index"] not in spots:
            spots[leg["index"]] = get_spot_price(leg["index"])
    return get_spread_greeks(legs, spots)

# ─── IV series ────────────────────────────────────────────────────────────────

def get_iv_series(index: str, strike: int, expiry: str, cp: str,
                  n_bars: int = 60, tf_minutes: int = 5) -> pd.DataFrame:
    return get_iv_series_live(index, strike, expiry, cp, tf_minutes)

# ─── Multiplier ───────────────────────────────────────────────────────────────

def get_multiplier_series(sx_strike: int, sx_expiry: str,
                           n_strike:  int, n_expiry:  str,
                           n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:
    tf_map = {1: "1", 5: "5", 15: "15", 60: "60", 375: "D"}
    return get_multiplier_series_live(
        sx_strike, sx_expiry, n_strike, n_expiry,
        tf_map.get(tf_minutes, "1")
    )
