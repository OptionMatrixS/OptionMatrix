"""
Tab 3 — IV Calculator (up to 5 expiries on the same strike)
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import math

from fyers_data import (
    fetch_option_chain, parse_option_chain, build_symbol,
    fetch_ltp, fetch_spot, fetch_candles
)
from bs_math import implied_volatility
from ui_utils import dark_layout, stat_chips_row, now_ist, BLUE, GREEN, RED, ORANGE, PURPLE


EXPIRY_COLORS = [BLUE, GREEN, ORANGE, RED, PURPLE]


def render(fyers):
    st.header("📈 IV Calculator")

    chain_cache = st.session_state.setdefault("chain_cache_t3", {})

    col1, col2, col3, col4 = st.columns([1, 1.2, 1, 1])
    index    = col1.selectbox("Index", ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"], key="iv_index")
    opt_type = col4.selectbox("Option Type", ["CE", "PE"], key="iv_ot")
    tf       = col4.selectbox("Timeframe", ["1m", "5m", "15m", "1h"], index=1, key="iv_tf")

    # Load chain
    ck = f"chain_{index}"
    if ck not in chain_cache:
        resp = fetch_option_chain(fyers, index)
        expiries, strikes, chain_map = parse_option_chain(resp, index)
        chain_cache[ck] = {"expiries": expiries, "strikes": strikes}

    cd = chain_cache.get(ck, {})
    expiries = cd.get("expiries", [])
    strikes  = cd.get("strikes", [])

    strike = col2.selectbox("Strike", strikes,
                            index=len(strikes)//2 if strikes else 0,
                            key="iv_strike")

    # Up to 5 expiry selections
    st.markdown("**Select up to 5 Expiries**")
    exp_cols = st.columns(5)
    selected_expiries = []
    for i in range(5):
        e = exp_cols[i].selectbox(
            f"Expiry {i+1}", ["—"] + expiries,
            key=f"iv_exp_{i}", label_visibility="collapsed"
        )
        if e != "—":
            selected_expiries.append(e)

    if not selected_expiries:
        st.info("Select at least one expiry above.")
        return

    spot = fetch_spot(fyers, index)
    T_ref = 7 / 365  # default T if no date info

    # IV live feed
    iv_history = st.session_state.setdefault("iv_history", {e: [] for e in selected_expiries})

    col_s, col_stop, col_clr = st.columns(3)
    if col_s.button("▶ Start", key="iv_start"):
        st.session_state["iv_live_on"] = True
        st.rerun()
    if col_stop.button("⏹ Stop", key="iv_stop"):
        st.session_state["iv_live_on"] = False
    if col_clr.button("🗑 Clear", key="iv_clear"):
        st.session_state["iv_history"] = {e: [] for e in selected_expiries}
        iv_history = {}

    def _compute_ivs():
        syms = {e: build_symbol(index, e, strike, opt_type) for e in selected_expiries}
        ltp_data = fetch_ltp(fyers, list(syms.values()))
        result = {}
        for e, sym in syms.items():
            ltp = ltp_data.get(sym, {}).get("ltp", 0)
            iv  = implied_volatility(ltp, spot or strike, strike, T_ref, 0.065, opt_type)
            result[e] = {"iv": round(iv * 100, 2), "ltp": ltp}
        return result

    # Stat chips
    try:
        ivs = _compute_ivs()
        chips = [(e[:12], f"{ivs[e]['iv']:.1f}%", "blue") for e in selected_expiries]
        stat_chips_row(chips)
    except Exception as e:
        st.warning(f"IV fetch error: {e}")

    # Chart
    fig = go.Figure()
    for idx_e, exp in enumerate(selected_expiries):
        hist = iv_history.get(exp, [])
        if hist:
            df = pd.DataFrame(hist)
            fig.add_trace(go.Scatter(
                x=df["ts"], y=df["iv"],
                name=exp[:16],
                line=dict(color=EXPIRY_COLORS[idx_e % len(EXPIRY_COLORS)], width=2)
            ))

    if any(iv_history.get(e) for e in selected_expiries):
        fig.update_layout(**dark_layout("Implied Volatility % Over Time", 400))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Start live feed to see IV chart.")

    # Live tick
    if st.session_state.get("iv_live_on"):
        try:
            ivs = _compute_ivs()
            ts  = now_ist()
            for e in selected_expiries:
                if e not in st.session_state["iv_history"]:
                    st.session_state["iv_history"][e] = []
                st.session_state["iv_history"][e].append({"ts": ts, "iv": ivs[e]["iv"]})
        except Exception:
            pass
        import time; time.sleep(3)
        st.rerun()
