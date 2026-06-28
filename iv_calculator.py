"""iv_calculator.py — Tab 3: IV across up to 5 expiries (same index/strike)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import styles
import fyers_client as fc
from spread_chart import INDICES, _expiries, _strikes

P = styles.PALETTE
_LINE_COLORS = [P["BLUE"], P["GREEN"], P["ORANGE"], P["PURPLE"], P["CYAN"]]


def _years_from(ts: pd.Timestamp, expiry_date) -> float:
    exp_dt = datetime(expiry_date.year, expiry_date.month, expiry_date.day, 15, 30)
    secs = (exp_dt - ts.to_pydatetime()).total_seconds()
    return max(secs, 0.0) / (365.0 * 24 * 3600)


def _iv_series(index, expiry_label, strike, opt_type, under_df, dfrom, dto, res):
    e = fc.find_expiry(index, expiry_label)
    if not e:
        return None
    opt = fc.get_candles(fc.build_symbol(index, e["code"], opt_type, strike),
                         dfrom, dto, res)
    if opt.empty or under_df.empty:
        return None
    o = opt.set_index("ts")["close"]
    u = under_df.set_index("ts")["close"]
    df = o.rename("price").to_frame().join(u.rename("spot"), how="inner").dropna()
    ivs = []
    for ts, row in df.iterrows():
        t = _years_from(ts, e["date"])
        iv = fc.implied_vol(row["price"], row["spot"], float(strike), t, opt_type)
        ivs.append(iv * 100 if iv else None)
    return pd.Series(ivs, index=df.index).dropna()


def render(user):
    c = st.columns([1.2, 1.4, 1, 1])
    index = c[0].selectbox("Index", INDICES, key="iv_idx")
    exps = _expiries(index)
    chosen = c[1].multiselect("Expiries (max 5)", exps, default=exps[:2],
                              key="iv_exps", max_selections=5)
    strikes = _strikes(index, chosen[0] if chosen else (exps[0] if exps else ""))
    strike = c[2].selectbox("Strike", strikes or [0], key="iv_stk",
                            index=len(strikes) // 2 if strikes else 0)
    opt_type = c[3].selectbox("Type", ["CE", "PE"], key="iv_ot")

    if not exps:
        st.caption("Waiting for Fyers expiry data…")
        return

    if st.button("🌡️ Compute IV", key="iv_btn"):
        if not chosen:
            st.warning("Pick at least one expiry.")
            return
        is_open, now = fc.market_status()
        today = now.date().isoformat()
        res = fc.resolution_for("5m")
        try:
            under = fc.get_candles(fc.INDEX_SYMBOLS[index], today, today, res)
        except Exception as e:
            st.error(f"Underlying candle fetch failed: {e}")
            return

        fig = go.Figure()
        chip_items = []
        any_series = False
        for i, exp in enumerate(chosen):
            try:
                ser = _iv_series(index, exp, strike, opt_type, under,
                                 today, today, res)
            except Exception as e:
                st.caption(f"{exp}: {e}")
                continue
            if ser is None or ser.empty:
                # live snapshot fallback
                e_obj = fc.find_expiry(index, exp)
                spot = fc.underlying_ltp(index)
                price = fc.get_quote(
                    fc.build_symbol(index, e_obj["code"], opt_type, strike)
                ).get("ltp", 0.0)
                t = fc.years_to_expiry(e_obj["date"])
                iv = fc.implied_vol(price, spot, float(strike), t, opt_type)
                if iv:
                    chip_items.append((exp.split("(")[0].strip(),
                                       f"{iv*100:,.2f}", _LINE_COLORS[i % 5]))
                continue
            any_series = True
            fig.add_trace(go.Scatter(x=ser.index, y=ser.values, mode="lines",
                                     name=exp, line=dict(color=_LINE_COLORS[i % 5],
                                                         width=2)))
            chip_items.append((exp.split("(")[0].strip(),
                               f"cur {ser.values[-1]:,.1f} · "
                               f"hi {ser.max():,.1f} · lo {ser.min():,.1f}",
                               _LINE_COLORS[i % 5]))

        if any_series:
            fig.update_layout(**styles.plotly_layout("Implied Volatility %", 440))
            st.plotly_chart(fig, use_container_width=True, key="iv_chart")
        else:
            st.info("No intraday candles — showing live IV snapshots only.")

        if chip_items:
            st.markdown(styles.chips_row(chip_items), unsafe_allow_html=True)
