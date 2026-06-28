"""historical_backtest.py — Tab 5: replay a spread over a past trading day."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import styles
import fyers_client as fc
from spread_chart import build_legs, valid_legs, _spread_candles

P = styles.PALETTE


def _last_weekday() -> date:
    d = fc.ist_now().date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _filter_market_hours(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    t = df["ts"].dt.time
    start = pd.to_datetime("09:15").time()
    end = pd.to_datetime("15:30").time()
    return df[(t >= start) & (t <= end)].reset_index(drop=True)


def render(user):
    top = st.columns([1, 1, 1])
    n_legs = top[0].number_input("Number of Legs", 2, 6, 2, key="bt_nlegs")
    day = top[1].date_input("Trading day", value=_last_weekday(),
                            max_value=fc.ist_now().date(), key="bt_day")
    timeframe = top[2].selectbox("Timeframe", list(fc.TIMEFRAMES.keys()),
                                 key="bt_tf")

    st.markdown(styles.section("Legs"), unsafe_allow_html=True)
    legs = build_legs("bt", int(n_legs))
    st.session_state["legs_backtest"] = legs

    if st.button("🕰️ Run Backtest", key="bt_run"):
        vl = valid_legs(legs)
        if not vl:
            st.warning("Add at least one valid leg.")
            return
        if day.weekday() >= 5:
            st.warning("Selected day is a weekend — no market data.")
            return
        d = day.isoformat()
        try:
            res = fc.resolution_for(timeframe)
            df = _spread_candles(vl, d, d, res)
        except Exception as e:
            st.error(f"Candle fetch failed: {e}")
            return
        df = _filter_market_hours(df)
        if df.empty:
            st.info("No candle data for that day (holiday, or before listing).")
            return

        op, cl = df["o"].iloc[0], df["c"].iloc[-1]
        hi, lo = df["h"].max(), df["l"].min()
        chg = ((cl - op) / op * 100) if op else 0.0

        fig = go.Figure(go.Candlestick(
            x=df["ts"], open=df["o"], high=df["h"], low=df["l"], close=df["c"],
            increasing_line_color=P["GREEN"], decreasing_line_color=P["RED"],
            name="Spread"))
        fig.add_hline(y=hi, line_dash="dot", line_color=P["GREEN"],
                      annotation_text=f"Day High {hi:,.1f}")
        fig.add_hline(y=lo, line_dash="dot", line_color=P["RED"],
                      annotation_text=f"Day Low {lo:,.1f}")
        lay = styles.plotly_layout(f"Spread · {d}", 440)
        lay["xaxis"]["rangeslider"] = dict(visible=False)
        fig.update_layout(**lay)
        st.plotly_chart(fig, use_container_width=True, key="bt_chart")

        chg_color = P["GREEN"] if chg >= 0 else P["RED"]
        st.markdown(styles.chips_row([
            ("Open", f"{op:,.2f}", P["TEXT"]),
            ("Close", f"{cl:,.2f}", P["TEXT"]),
            ("High", f"{hi:,.2f}", P["GREEN"]),
            ("Low", f"{lo:,.2f}", P["RED"]),
            ("Change %", f"{chg:+.2f}%", chg_color),
        ]), unsafe_allow_html=True)

        st.markdown(styles.section("Candle data"), unsafe_allow_html=True)
        out = df.copy()
        out.columns = ["Time", "Open", "High", "Low", "Close"]
        st.dataframe(out, use_container_width=True, hide_index=True, height=280)

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xl:
            out.to_excel(xl, index=False, sheet_name="Backtest")
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Excel", buf.getvalue(),
                           file_name=f"backtest_{d}.xlsx", key="bt_xl",
                           mime="application/vnd.openxmlformats-officedocument."
                                "spreadsheetml.sheet")
        c2.download_button("⬇️ CSV", out.to_csv(index=False).encode(),
                           file_name=f"backtest_{d}.csv", key="bt_csv",
                           mime="text/csv")
