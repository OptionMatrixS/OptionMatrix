"""
Tab 2 — Multiplier Chart (SENSEX/NIFTY Synthetic Futures Ratio)
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from fyers_data import (
    fetch_option_chain, parse_option_chain, build_symbol,
    fetch_ltp, fetch_candles, is_market_closed
)
from ui_utils import dark_layout, stat_chips_row, market_closed_notice, now_ist, BLUE, GREEN, RED, ORANGE


def _get_chain(fyers, index: str, cache: dict):
    key = f"chain_{index}"
    if key not in cache:
        resp = fetch_option_chain(fyers, index)
        expiries, strikes, chain_map = parse_option_chain(resp, index)
        cache[key] = {"expiries": expiries, "strikes": strikes}
    return cache[key]


def render(fyers):
    st.header("✖️ Multiplier Chart — SENSEX / NIFTY Ratio")

    chain_cache = st.session_state.setdefault("chain_cache_t2", {})

    col1, col2, col3, col4 = st.columns(4)

    # SENSEX inputs
    sx_chain = _get_chain(fyers, "SENSEX", chain_cache)
    sx_expiry = col1.selectbox("SENSEX Expiry", sx_chain.get("expiries", [""]), key="sx_exp_t2")
    sx_strikes = sx_chain.get("strikes", [79000])
    sx_default = sx_strikes[len(sx_strikes)//2] if sx_strikes else 79000
    sx_strike  = col2.selectbox("SENSEX Strike", sx_strikes,
                                index=sx_strikes.index(sx_default) if sx_default in sx_strikes else 0,
                                key="sx_str_t2")

    # NIFTY inputs
    nf_chain = _get_chain(fyers, "NIFTY", chain_cache)
    nf_expiry = col3.selectbox("NIFTY Expiry", nf_chain.get("expiries", [""]), key="nf_exp_t2")
    nf_strikes = nf_chain.get("strikes", [24000])
    nf_default = nf_strikes[len(nf_strikes)//2] if nf_strikes else 24000
    nf_strike  = col4.selectbox("NIFTY Strike", nf_strikes,
                                index=nf_strikes.index(nf_default) if nf_default in nf_strikes else 0,
                                key="nf_str_t2")

    tf = st.selectbox("Timeframe", ["1m", "5m", "15m", "1h"], index=1, key="tf_t2")

    mult_history = st.session_state.setdefault("mult_history", [])
    live_on = st.session_state.get("mult_live_on", False)

    col_start, col_stop, col_clear = st.columns(3)
    if col_start.button("▶ Start", disabled=live_on, key="mult_start"):
        st.session_state["mult_live_on"] = True
        st.rerun()
    if col_stop.button("⏹ Stop", key="mult_stop"):
        st.session_state["mult_live_on"] = False
    if col_clear.button("🗑 Clear", key="mult_clear"):
        st.session_state["mult_history"] = []
        mult_history = []

    def _fetch_mult():
        """Fetch current multiplier value."""
        sx_ce_sym = build_symbol("SENSEX", sx_expiry, sx_strike, "CE")
        sx_pe_sym = build_symbol("SENSEX", sx_expiry, sx_strike, "PE")
        nf_ce_sym = build_symbol("NIFTY",  nf_expiry, nf_strike, "CE")
        nf_pe_sym = build_symbol("NIFTY",  nf_expiry, nf_strike, "PE")

        all_syms = [sx_ce_sym, sx_pe_sym, nf_ce_sym, nf_pe_sym]
        ltp_data = fetch_ltp(fyers, all_syms)

        sx_ce = ltp_data.get(sx_ce_sym, {}).get("ltp", 0)
        sx_pe = ltp_data.get(sx_pe_sym, {}).get("ltp", 0)
        nf_ce = ltp_data.get(nf_ce_sym, {}).get("ltp", 0)
        nf_pe = ltp_data.get(nf_pe_sym, {}).get("ltp", 0)

        sx_synth = sx_strike + sx_ce - sx_pe
        nf_synth = nf_strike + nf_ce - nf_pe

        mult = sx_synth / nf_synth if nf_synth != 0 else 0

        closed = is_market_closed(ltp_data)
        return mult, sx_synth, nf_synth, closed

    # Snapshot for stat chips
    if sx_expiry and nf_expiry:
        try:
            mult, sx_synth, nf_synth, closed = _fetch_mult()
            if closed:
                market_closed_notice()

            hist_vals = [h["mult"] for h in mult_history] if mult_history else [mult]
            stat_chips_row([
                ("Current Multiplier", f"{mult:.4f}", "blue"),
                ("SENSEX Synthetic",   f"₹{sx_synth:,.2f}", "text"),
                ("NIFTY Synthetic",    f"₹{nf_synth:,.2f}", "text"),
                ("Session High",  f"{max(hist_vals):.4f}", "green"),
                ("Session Low",   f"{min(hist_vals):.4f}", "red"),
            ])
        except Exception as e:
            st.error(f"Fetch error: {e}")

    # Chart
    if mult_history:
        df = pd.DataFrame(mult_history)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["ts"], y=df["mult"],
                                 line=dict(color=BLUE, width=2), name="Multiplier"))
        # Reference line at 3.25
        fig.add_hline(y=3.25, line_dash="dot", line_color=ORANGE, annotation_text="3.25×")
        fig.update_layout(**dark_layout("SENSEX/NIFTY Multiplier", 400))
        st.plotly_chart(fig, use_container_width=True)

        # Sub-charts: synthetic prices
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["ts"], y=df["sx_synth"], name="SENSEX Synth",
                                  line=dict(color=GREEN)))
        fig2.update_layout(**dark_layout("SENSEX Synthetic Price", 250))
        st.plotly_chart(fig2, use_container_width=True)

        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=df["ts"], y=df["nf_synth"], name="NIFTY Synth",
                                  line=dict(color=RED)))
        fig3.update_layout(**dark_layout("NIFTY Synthetic Price", 250))
        st.plotly_chart(fig3, use_container_width=True)

    # Live tick
    if st.session_state.get("mult_live_on") and sx_expiry and nf_expiry:
        try:
            mult, sx_synth, nf_synth, closed = _fetch_mult()
            ts = now_ist()
            st.session_state["mult_history"].append({
                "ts": ts, "mult": mult,
                "sx_synth": sx_synth, "nf_synth": nf_synth
            })
        except Exception:
            pass
        import time; time.sleep(3)
        st.rerun()
