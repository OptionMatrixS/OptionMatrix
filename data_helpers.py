# At top of data_helpers.py
from dhan_client import get_live_ltp, get_live_spread_ohlcv

# Replace get_option_price()
def get_option_price(index, strike, expiry, cp):
    try:
        return get_live_ltp(index, strike, expiry, cp)
    except Exception:
        return _sample_price(index, strike, expiry, cp)  # fallback

# Replace generate_spread_ohlcv()
def generate_spread_ohlcv(legs, tf_minutes=1):
    tf_map = {1:"1", 5:"5", 15:"15", 60:"60", 375:"D"}
    try:
        return get_live_spread_ohlcv(legs, tf_map.get(tf_minutes, "1"))
    except Exception:
        return _sample_ohlcv(25, 80, tf_minutes)
