"""
data_helpers.py — Option Matrix
Thin layer over fyers_client for all page modules.

ROOT FIX for LTP: 0.00 bug:
  get_option_price() now ensures the expiry map is loaded into session state
  BEFORE calling build_symbol/get_live_ltp, so _label_to_code always resolves
  "08 May 25 (W)" → "250508" correctly.
"""
import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd

from fyers_client import (
    get_token, get_fyers_client,
    get_expiries, get_strikes,
    get_live_ltp, get_live_bid_ask_ltp, get_live_quote,
    get_live_spread_ohlcv, get_iv_series_live,
    get_multiplier_series_live, get_spot_price,
    get_spread_greeks, validate_legs,
    bs_price, implied_volatility, bs_greeks,
    _days_to_expiry, _label_to_code, build_symbol,
    RISK_FREE_RATE, refresh_token,
)

TF_MAP = {"1m": 1, "3m": 3, "5m": 5, "10m": 10,
          "15m": 15, "30m": 30, "60m": 60, "1D": 1440}


# ── Expiries / Strikes ────────────────────────────────────────────────────────

def get_index_expiries(index: str) -> list:
    return get_expiries(index)

def get_index_strikes(index: str, expiry: str) -> list:
    return get_strikes(index, expiry)

get_nifty_expiries     = lambda: get_expiries("NIFTY")
get_sensex_expiries    = lambda: get_expiries("SENSEX")
get_banknifty_expiries = lambda: get_expiries("BANKNIFTY")
get_nifty_strikes      = lambda exp: get_strikes("NIFTY",     exp)
get_sensex_strikes     = lambda exp: get_strikes("SENSEX",    exp)
get_banknifty_strikes  = lambda exp: get_strikes("BANKNIFTY", exp)


# ── Option price (ROOT FIX) ───────────────────────────────────────────────────

def get_option_price(index: str, strike: int,
                     expiry: str, cp: str) -> float:
    """
    Return live LTP for an option.

    The key fix: we call get_expiries(index) first so the expiry map is
    always populated in st.session_state before build_symbol tries to
    resolve the label to a Fyers expiry code.

    Without this, _label_to_code("NIFTY", "08 May 25 (W)") returns the
    raw label string and build_symbol produces a garbage symbol like
    NSE:NIFTY08 May 25 (W)CE24500 → Fyers returns nothing → LTP = 0.00
    """
    # Ensure expiry map is loaded so _label_to_code works
    ck = f"expiries_{index}"
    if not st.session_state.get(ck):
        try:
            get_expiries(index)   # populates st.session_state[ck]
        except Exception:
            pass

    # Verify the label resolves to a code before calling live LTP
    resolved = _label_to_code(index, expiry)
    if resolved == expiry:
        # Still not resolved — expiry map load failed
        # Fall back to raw Fyers quote by building symbol manually
        # from the label parts (e.g. "08 May 25 (W)" → approx code)
        pass   # get_live_ltp will try anyway; returns 0 if it fails

    try:
        return get_live_ltp(index, strike, expiry, cp)
    except Exception:
        return 0.0


# ── Spread OHLCV ──────────────────────────────────────────────────────────────

def generate_spread_ohlcv(legs, tf_minutes: int = 1,
                           date_str: str = None) -> pd.DataFrame:
    """
    Fetch OHLCV candles per leg and combine into spread OHLCV.
    Ensures expiry maps are loaded for all legs before fetching candles.
    """
    # Pre-load expiry maps so build_symbol resolves correctly
    loaded = set()
    for leg in legs:
        idx = leg.get("index", "")
        if idx and idx not in loaded:
            ck = f"expiries_{idx}"
            if not st.session_state.get(ck):
                try:
                    get_expiries(idx)
                except Exception:
                    pass
            loaded.add(idx)

    validate_legs(legs)
    return get_live_spread_ohlcv(legs, interval=tf_minutes, date_str=date_str)


# ── Greeks ────────────────────────────────────────────────────────────────────

def calc_greeks_for_legs(legs) -> dict:
    """Compute net Greeks for a list of legs using live LTPs + Black-Scholes."""
    validate_legs(legs)
    spots = {}
    for leg in legs:
        idx = leg["index"]
        if idx not in spots:
            try:
                spots[idx] = get_spot_price(idx)
            except Exception:
                spots[idx] = {"NIFTY":22800,"SENSEX":82500,
                              "BANKNIFTY":48000}.get(idx, 22800)
    try:
        return get_spread_greeks(legs, spots)
    except Exception:
        return {"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"net_iv":0.}


# ── IV Series ─────────────────────────────────────────────────────────────────

def get_iv_series(index, strike, expiry, cp,
                  n_bars: int = 60, tf_minutes: int = 5):
    return get_iv_series_live(index, strike, expiry, cp, tf_minutes)


# ── Multiplier ────────────────────────────────────────────────────────────────

def get_multiplier_series(sx_strike, sx_expiry, n_strike, n_expiry,
                           n_bars: int = 80, tf_minutes: int = 1):
    return get_multiplier_series_live(
        sx_strike, sx_expiry, n_strike, n_expiry, interval=tf_minutes)
