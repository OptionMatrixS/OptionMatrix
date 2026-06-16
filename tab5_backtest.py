"""
Tab 5 — Historical Backtest
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO

from fyers_data import (
    fetch_option_chain, parse_option_chain, build_symbol,
    fetch_candles, LOT_SIZES
)
from ui_utils import dark_layout, stat_chips_row, GREEN, RED, BLUE, ORANGE


def render(fyers):
    st.header("🕐 Historical Backtest")

    chain_cache = st.session_state.setdefault("chain_cache_t5", {})

    col_n, col_ct, col_tf = st.columns(3)
    n_legs     = col_n.number_input("Legs", 2, 6, 2, key="n_legs_t5")
    chart_type = col_ct.selectbox("Chart Type", ["Candlestick", "Line"], key="ct_t5")
    tf         = col_tf.selectbox("Timeframe", ["1m", "5m", "15m", "1h"], index=1, key="tf_t5")

    col_date, col_ts, col_te = st.columns([1, 1, 1])
    import datetime
    hist_date  = col_date.date_input("Date", value=datetime.date.today() - datetime.timedelta(days=1))
    time_start = col_ts.time_input("From", value=datetime.time(9, 15))
    time_end   = col_te.time_input("To",   value=datetime.time(15, 30))

    st.markdown("**Configure Legs**")
    legs = []
    for i in range(n_legs):
        c1, c2, c3, c4, c5 = st.columns([1, 1.5, 1.2, 0.8, 0.8])
        index = c1.selectbox("Index", ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"],
                             key=f"bt_idx_{i}")
        ck = f"chain_{index}"
        if ck not in chain_cache:
            resp = fetch_option_chain(fyers, index)
            expiries, strikes, _ = parse_option_chain(resp, index)
            chain_cache[ck] = {"expiries": expiries, "strikes": strikes}
        cd = chain_cache.get(ck, {})
        expiry  = c2.selectbox("Expiry",  cd.get("expiries", [""]), key=f"bt_exp_{i}")
        strikes = cd.get("strikes", [0])
        strike  = c3.selectbox("Strike",  strikes,
                               index=len(strikes)//2 if strikes else 0,
                               key=f"bt_str_{i}")
        opt_type  = c4.selectbox("Type", ["CE", "PE"], key=f"bt_ot_{i}")
        direction = c5.selectbox("Dir",  ["Buy", "Sell"], key=f"bt_dir_{i}")

        if expiry and strike:
            legs.append({
                "index": index, "expiry": expiry, "strike": strike,
                "opt_type": opt_type, "direction": direction,
                "symbol": build_symbol(index, expiry, strike, opt_type),
            })

    if st.button("📊 Load Historical Data", use_container_width=True) and legs:
        date_str = hist_date.strftime("%Y-%m-%d")
        spread_df = None

        for leg in legs:
            df_c = fetch_candles(fyers, leg["symbol"], tf, date_str, date_str)
            if df_c.empty:
                st.warning(f"No data for {leg['symbol']}")
                continue
            # Filter time range
            df_c = df_c[
                (df_c["datetime"].dt.time >= time_start) &
                (df_c["datetime"].dt.time <= time_end)
            ]
            sign = -1 if leg["direction"] == "Sell" else 1
            df_c = df_c.set_index("datetime") * sign
            spread_df = df_c if spread_df is None else spread_df.add(df_c, fill_value=0)

        if spread_df is not None and not spread_df.empty:
            spread_df = spread_df.reset_index()

            day_high  = spread_df["high"].max()
            day_low   = spread_df["low"].min()
            day_open  = spread_df["open"].iloc[0]
            day_close = spread_df["close"].iloc[-1]
            change_pct = (day_close - day_open) / day_open * 100 if day_open != 0 else 0

            stat_chips_row([
                ("Open",   f"{day_open:.2f}",   "text"),
                ("Close",  f"{day_close:.2f}",  "blue"),
                ("High",   f"{day_high:.2f}",   "green"),
                ("Low",    f"{day_low:.2f}",    "red"),
                ("Change", f"{change_pct:+.2f}%", "green" if change_pct >= 0 else "red"),
            ])

            # Chart
            fig = go.Figure()
            if chart_type == "Candlestick":
                fig.add_trace(go.Candlestick(
                    x=spread_df["datetime"],
                    open=spread_df["open"], high=spread_df["high"],
                    low=spread_df["low"],   close=spread_df["close"],
                    increasing_line_color=GREEN,
                    decreasing_line_color=RED,
                ))
            else:
                fig.add_trace(go.Scatter(x=spread_df["datetime"], y=spread_df["close"],
                                         line=dict(color=BLUE, width=2)))

            fig.add_hline(y=day_high, line_dash="dash", line_color=GREEN,
                          annotation_text=f"High {day_high:.2f}")
            fig.add_hline(y=day_low,  line_dash="dash", line_color=RED,
                          annotation_text=f"Low {day_low:.2f}")
            fig.update_layout(**dark_layout(f"Spread — {hist_date}", 420))
            st.plotly_chart(fig, use_container_width=True)

            # Data table
            st.dataframe(spread_df, use_container_width=True, height=300)

            # Export
            col_e1, col_e2 = st.columns(2)
            buf = BytesIO()
            spread_df.to_excel(buf, index=False)
            col_e1.download_button("📥 Export Excel", buf.getvalue(),
                                   file_name=f"backtest_{hist_date}.xlsx")
            col_e2.download_button("📥 Export CSV", spread_df.to_csv(index=False),
                                   file_name=f"backtest_{hist_date}.csv")
        else:
            st.warning("No candle data available for the selected date/legs.")
