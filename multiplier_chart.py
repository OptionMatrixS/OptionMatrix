"""multiplier_chart.py — Tab 2: SENSEX/NIFTY synthetic-future multiplier.

Multiplier = (SENSEX_strike + SENSEX_CE - SENSEX_PE)
           / (NIFTY_strike  + NIFTY_CE  - NIFTY_PE)
i.e. the ratio of the two synthetic futures implied by ATM call/put parity.
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

import styles
import fyers_client as fc
from spread_chart import _expiries, _strikes, _nearest_index

P = styles.PALETTE


def _syn_future_series(index, expiry, strike, dfrom, dto, res):
    """Per-bar (strike + CE_close - PE_close) aligned on timestamp."""
    e = fc.find_expiry(index, expiry)
    code = e["code"] if e else expiry
    ce = fc.get_candles(fc.build_symbol(index, code, "CE", strike), dfrom, dto, res)
    pe = fc.get_candles(fc.build_symbol(index, code, "PE", strike), dfrom, dto, res)
    if ce.empty or pe.empty:
        return None
    ce = ce.set_index("ts")["close"]
    pe = pe.set_index("ts")["close"]
    syn = (ce - pe + float(strike)).dropna()
    return syn


def _syn_future_point(index, expiry, strike):
    e = fc.find_expiry(index, expiry)
    code = e["code"] if e else expiry
    q = fc.get_quotes([fc.build_symbol(index, code, "CE", strike),
                       fc.build_symbol(index, code, "PE", strike)])
    ce = q.get(fc.build_symbol(index, code, "CE", strike), {}).get("ltp", 0.0)
    pe = q.get(fc.build_symbol(index, code, "PE", strike), {}).get("ltp", 0.0)
    return float(strike) + ce - pe


def render(user):
    c = st.columns(5)
    s_exps = _expiries("SENSEX")
    s_exp = c[0].selectbox("SENSEX Expiry", s_exps or ["—"], key="mx_s_exp")
    s_stk_list = _strikes("SENSEX", s_exp if s_exps else "")
    s_strike = c[1].selectbox("SENSEX Strike", s_stk_list or [0], key="mx_s_stk",
                              index=len(s_stk_list) // 2 if s_stk_list else 0)
    n_exps = _expiries("NIFTY")
    n_exp = c[2].selectbox("NIFTY Expiry", n_exps or ["—"], key="mx_n_exp")
    n_stk_list = _strikes("NIFTY", n_exp if n_exps else "")
    n_strike = c[3].selectbox("NIFTY Strike", n_stk_list or [0], key="mx_n_stk",
                              index=len(n_stk_list) // 2 if n_stk_list else 0)
    timeframe = c[4].selectbox("Timeframe", list(fc.TIMEFRAMES.keys()), key="mx_tf")

    if not (s_exps and n_exps):
        st.caption("Waiting for Fyers expiry data…")
        return

    if st.button("📈 Plot Multiplier", key="mx_btn"):
        is_open, now = fc.market_status()
        today = now.date().isoformat()
        res = fc.resolution_for(timeframe)
        try:
            s_syn = _syn_future_series("SENSEX", s_exp, s_strike, today, today, res)
            n_syn = _syn_future_series("NIFTY", n_exp, n_strike, today, today, res)
        except Exception as e:
            st.error(f"Candle fetch failed: {e}")
            return

        if s_syn is not None and n_syn is not None:
            df = (s_syn.rename("s").to_frame()
                  .join(n_syn.rename("n"), how="inner").dropna())
            df = df[df["n"] != 0]
            if df.empty:
                st.info("No overlapping candle timestamps.")
                return
            mult = (df["s"] / df["n"])
            fig = go.Figure(go.Scatter(x=mult.index, y=mult.values, mode="lines",
                                       line=dict(color=P["BLUE"], width=2)))
            fig.update_layout(**styles.plotly_layout("Multiplier over time", 420))
            st.plotly_chart(fig, use_container_width=True, key="mx_chart")
            vals = mult.values
            cur, avg, hi, lo = vals[-1], vals.mean(), vals.max(), vals.min()
        else:
            # market closed / no intraday — single live-quote point
            try:
                s_pt = _syn_future_point("SENSEX", s_exp, s_strike)
                n_pt = _syn_future_point("NIFTY", n_exp, n_strike)
            except Exception as e:
                st.error(f"Quote fetch failed: {e}")
                return
            if n_pt == 0:
                st.warning("NIFTY synthetic future is zero — check inputs.")
                return
            cur = avg = hi = lo = s_pt / n_pt
            st.info("Market closed / no intraday candles — showing a single "
                    "live-quote snapshot.")

        st.markdown(styles.chips_row([
            ("Current", f"{cur:,.4f}", P["BLUE"]),
            ("Average", f"{avg:,.4f}", P["TEXT"]),
            ("High", f"{hi:,.4f}", P["GREEN"]),
            ("Low", f"{lo:,.4f}", P["RED"]),
        ]), unsafe_allow_html=True)
