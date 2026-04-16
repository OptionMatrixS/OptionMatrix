"""data_helpers.py — All live data via Fyers API"""
import pandas as pd
from fyers_client import (
    get_live_ltp, get_live_bid_ask_ltp, get_live_quote,
    get_live_spread_ohlcv, get_iv_series_live,
    get_multiplier_series_live, get_spot_price,
    get_spread_greeks, get_expiries, get_strikes,
    validate_legs, bs_price, implied_volatility,
    bs_greeks, _days_to_expiry, RISK_FREE_RATE,
    refresh_token,
)

TF_MAP = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}

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

# ── Option price ──────────────────────────────────────────────────────────────
def get_option_price(index: str, strike: int, expiry: str, cp: str) -> float:
    return get_live_ltp(index, strike, expiry, cp)

# ── Spread BID/ASK/LTP ────────────────────────────────────────────────────────
def get_spread_bid_ask_ltp(legs: list, strikes_per_leg: list) -> tuple:
    bid_total = ask_total = ltp_total = 0.0
    for leg, strike in zip(legs, strikes_per_leg):
        bid, ask, ltp = get_live_bid_ask_ltp(
            leg["index"], strike, leg["expiry"], leg["cp"])
        sign = 1 if leg["bs"] == "Buy" else -1
        bid_total += sign * bid * leg["ratio"]
        ask_total += sign * ask * leg["ratio"]
        ltp_total += sign * ltp * leg["ratio"]
    return round(bid_total,2), round(ask_total,2), round(ltp_total,2)

# ── Spread OHLCV ──────────────────────────────────────────────────────────────
def generate_spread_ohlcv(legs: list, tf_minutes: int = 1,
                           date_str: str = None) -> pd.DataFrame:
    validate_legs(legs)
    return get_live_spread_ohlcv(legs, interval=tf_minutes, date_str=date_str)

# ── Greeks ────────────────────────────────────────────────────────────────────
def calc_greeks_for_legs(legs: list) -> dict:
    validate_legs(legs)
    spots = {}
    for leg in legs:
        if leg["index"] not in spots:
            spots[leg["index"]] = get_spot_price(leg["index"])
    return get_spread_greeks(legs, spots)

# ── IV Series ─────────────────────────────────────────────────────────────────
def get_iv_series(index: str, strike: int, expiry: str, cp: str,
                  n_bars: int = 60, tf_minutes: int = 5) -> pd.DataFrame:
    return get_iv_series_live(index, strike, expiry, cp, tf_minutes)

# ── Multiplier ────────────────────────────────────────────────────────────────
def get_multiplier_series(sx_strike: int, sx_expiry: str,
                           n_strike:  int, n_expiry:  str,
                           n_bars: int = 80, tf_minutes: int = 1) -> pd.DataFrame:
    return get_multiplier_series_live(
        sx_strike, sx_expiry, n_strike, n_expiry, interval=tf_minutes)
