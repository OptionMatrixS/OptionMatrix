"""
persist.py  —  Cross-session persistence for Option Matrix
Saves/loads user inputs to a JSON file keyed by username.
Works across tab switches, page reloads, and re-logins.
"""
import os, json, streamlit as st
from datetime import date

PERSIST_FILE = "user_state.json"

def _load_all() -> dict:
    try:
        with open(PERSIST_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_all(data: dict):
    try:
        with open(PERSIST_FILE, "w") as f:
            json.dump(data, f, default=str)
    except Exception:
        pass

def save_state(username: str, key: str, value):
    """Save a single key for a user."""
    all_data = _load_all()
    if username not in all_data:
        all_data[username] = {}
    # Serialise — skip un-serialisable objects (DataFrames etc.)
    try:
        json.dumps(value, default=str)
        all_data[username][key] = value
        _save_all(all_data)
    except Exception:
        pass

def load_state(username: str, key: str, default=None):
    """Load a single key for a user."""
    all_data = _load_all()
    return all_data.get(username, {}).get(key, default)

def save_user_session(username: str):
    """
    Snapshot all persist-able keys from st.session_state to disk.
    Called on every meaningful user action.
    """
    PERSIST_KEYS = [
        # Spread chart
        "sp_n_legs","sp_chart_type","sp_tf",
        # Multiplier
        "mx_sx_exp","mx_n_exp","mx_tf",
        # IV
        "iv_idx","iv_cp","iv_tf","iv_nexp",
        # Spread tracker
        "st_n_spreads","st_show_greeks","st_configs",
        # Historical
        "ht_n_legs","ht_chart_type","ht_interval",
        # Page
        "page",
    ]
    # Also save all sp_idx_i, sp_strike_i, sp_exp_i, sp_cp_i etc.
    for k in list(st.session_state.keys()):
        if any(k.startswith(p) for p in [
            "sp_idx_","sp_strike_","sp_exp_","sp_cp_","sp_bs_","sp_ratio_",
            "ht_idx_","ht_strike_","ht_exp_","ht_cp_","ht_bs_","ht_ratio_",
            "mx_sx_","mx_n_","iv_exp_",
            "st_","c_exch_","c_under_","c_str_","c_opt_","c_lots_",
        ]):
            PERSIST_KEYS.append(k)

    all_data = _load_all()
    if username not in all_data:
        all_data[username] = {}

    for key in set(PERSIST_KEYS):
        val = st.session_state.get(key)
        if val is None:
            continue
        try:
            json.dumps(val, default=str)
            all_data[username][key] = val
        except Exception:
            pass

    _save_all(all_data)


def restore_user_session(username: str):
    """
    Restore all saved keys into st.session_state.
    Called once after login.
    """
    all_data = _load_all()
    user_data = all_data.get(username, {})
    for key, val in user_data.items():
        if key not in st.session_state:
            st.session_state[key] = val
