"""data_helpers.py — All live data via Dhan API"""
import pandas as pd
from datetime import datetime
from dhan_client import (
    get_live_ltp, get_live_bid_ask_ltp, get_live_spread_ohlcv,
    get_iv_series_live, get_multiplier_series_live,
    get_expiries, get_strikes, get_spot_price,
    get_spread_greeks, get_live_quote,
    bs_price, implied_volatility, bs_greeks,
    _days_to_expiry, RISK_FREE_RATE
)

TF_MAP = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1D": 375}

def get_nifty_expiries():
    return get_expiries("NIFTY")

def get_sensex_expiries():
    return get_expiries("SENSEX")

def get_banknifty_expiries():
    return get_expiries("BANKNIFTY")

def get_index_expiries(index: str):
    return get_expiries(index)

def get_nifty_strikes(expiry):
    return get_strikes("NIFTY", expiry)

def get_sensex_strikes(expiry):
    return get_strikes("SENSEX", expiry)

def get_banknifty_strikes(expiry):
    return get_strikes("BANKNIFTY", expiry)

def get_index_strikes(index: str, expiry: str):
    return get_strikes(index, expiry)

def get_option_price(index, strike, expiry, cp):
    return get_live_ltp(index, strike, expiry, cp)

def get_spread_bid_ask_ltp(legs, strikes_per_leg):
    bid_total = ask_total = ltp_total = 0.0
    for leg, strike in zip(legs, strikes_per_leg):
        bid, ask, ltp = get_live_bid_ask_ltp(leg["index"], strike, leg["expiry"], leg["cp"])
        sign = 1 if leg["bs"] == "Buy" else -1
        bid_total += sign * bid * leg["ratio"]
        ask_total += sign * ask * leg["ratio"]
        ltp_total += sign * ltp * leg["ratio"]
    return round(bid_total,2), round(ask_total,2), round(ltp_total,2)

def generate_spread_ohlcv(legs, tf_minutes=1):
    tf_map = {1:"1",5:"5",15:"15",60:"60",375:"D"}
    return get_live_spread_ohlcv(legs, tf_map.get(tf_minutes,"1"))

def get_iv_series(index, strike, expiry, cp, n_bars=60, tf_minutes=5):
    return get_iv_series_live(index, strike, expiry, cp, tf_minutes)

def get_multiplier_series(sx_strike, sx_expiry, n_strike, n_expiry, n_bars=80, tf_minutes=1):
    tf_map = {1:"1",5:"5",15:"15",60:"60",375:"D"}
    return get_multiplier_series_live(sx_strike, sx_expiry, n_strike, n_expiry, tf_map.get(tf_minutes,"1"))

def calc_greeks_for_legs(legs):
    spots = {}
    for leg in legs:
        if leg["index"] not in spots:
            spots[leg["index"]] = get_spot_price(leg["index"])
    return get_spread_greeks(legs, spots)
