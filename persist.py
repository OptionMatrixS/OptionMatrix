"""
persist.py — Cross-session input persistence for Option Matrix.
Saves/restores user inputs to user_state.json.
Handles non-serializable types (set, DataFrame) gracefully.
"""
import os, json
import streamlit as st

PERSIST_FILE = "user_state.json"

def _safe_val(v):
    """Convert value to JSON-safe form."""
    if isinstance(v, set):   return list(v)
    if isinstance(v, (int, float, str, bool, list, dict, type(None))): return v
    try:
        json.dumps(v); return v
    except Exception:
        return None  # drop non-serialisable (DataFrames, Figures etc.)

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

def save_user_session(username: str):
    """Snapshot persist-able keys from st.session_state to disk."""
    PERSIST_KEYS = [
        "page",
        "sp_n_legs","sp_chart_type","sp_tf",
        "mx_tf","iv_tf","ht_n_legs","ht_chart_type",
        "st_n_spreads","st_show_greeks","sb_n_legs",
    ]
    for k in list(st.session_state.keys()):
        if any(k.startswith(p) for p in [
            "sp_idx_","sp_strike_","sp_exp_","sp_cp_","sp_bs_","sp_ratio_",
            "ht_idx_","ht_strike_","ht_exp_","ht_cp_","ht_bs_","ht_ratio_",
            "sb_idx_","sb_exp_","sb_bs_","sb_cp_","sb_strike_","sb_lots_",
            "mx_sx_","mx_n_","iv_exp_","st_",
            "sc_diff_","sc_n_rows",
        ]):
            PERSIST_KEYS.append(k)

    all_data = _load_all()
    if username not in all_data:
        all_data[username] = {}

    for key in set(PERSIST_KEYS):
        val = st.session_state.get(key)
        safe = _safe_val(val)
        if safe is not None:
            all_data[username][key] = safe

    _save_all(all_data)

def restore_user_session(username: str):
    """Restore saved keys into st.session_state. Called once after login."""
    all_data = _load_all()
    for key, val in all_data.get(username, {}).items():
        if key not in st.session_state:
            st.session_state[key] = val
