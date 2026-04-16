"""data_helpers.py — thin layer over fyers_client for all page modules."""
import pandas as pd
from fyers_client import (
    get_token, get_fyers_client, get_expiries, get_strikes,
    get_live_ltp, get_live_bid_ask_ltp, get_live_quote,
    get_live_spread_ohlcv, get_iv_series_live,
    get_multiplier_series_live, get_spot_price,
    get_spread_greeks, validate_legs, bs_price,
    implied_volatility, bs_greeks, _days_to_expiry,
    RISK_FREE_RATE, refresh_token,
)

TF_MAP = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}

# ── Expiries / Strikes ────────────────────────────────────────────────────────
def get_index_expiries(index: str) -> list:  return get_expiries(index)
def get_index_strikes(index: str, expiry: str) -> list: return get_strikes(index, expiry)

get_nifty_expiries     = lambda: get_expiries("NIFTY")
get_sensex_expiries    = lambda: get_expiries("SENSEX")
get_banknifty_expiries = lambda: get_expiries("BANKNIFTY")
get_nifty_strikes      = lambda exp: get_strikes("NIFTY",     exp)
get_sensex_strikes     = lambda exp: get_strikes("SENSEX",    exp)
get_banknifty_strikes  = lambda exp: get_strikes("BANKNIFTY", exp)

# ── Option price ──────────────────────────────────────────────────────────────
def get_option_price(index, strike, expiry, cp):
    return get_live_ltp(index, strike, expiry, cp)

# ── Spread OHLCV ──────────────────────────────────────────────────────────────
def generate_spread_ohlcv(legs, tf_minutes=1, date_str=None):
    validate_legs(legs)
    return get_live_spread_ohlcv(legs, interval=tf_minutes, date_str=date_str)

# ── Greeks ────────────────────────────────────────────────────────────────────
def calc_greeks_for_legs(legs):
    validate_legs(legs)
    spots = {leg["index"]: get_spot_price(leg["index"])
             for leg in legs if leg["index"] not in {}}
    return get_spread_greeks(legs, spots)

# ── IV Series ─────────────────────────────────────────────────────────────────
def get_iv_series(index, strike, expiry, cp, n_bars=60, tf_minutes=5):
    return get_iv_series_live(index, strike, expiry, cp, tf_minutes)

# ── Multiplier ────────────────────────────────────────────────────────────────
def get_multiplier_series(sx_strike, sx_expiry, n_strike, n_expiry,
                           n_bars=80, tf_minutes=1):
    return get_multiplier_series_live(
        sx_strike, sx_expiry, n_strike, n_expiry, interval=tf_minutes)
