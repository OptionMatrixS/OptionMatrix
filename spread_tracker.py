"""
Tab 1 — Spread Chart + Safety Calculator
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from io import BytesIO

from fyers_data import (
    fetch_option_chain, parse_option_chain, build_symbol,
    fetch_ltp, fetch_candles, LOT_SIZES, is_market_closed
)
from bs_math import bs_price, bs_greeks, implied_volatility
from ui_utils import (
    dark_layout, stat_chips_row, market_closed_notice,
    now_ist, GREEN, RED, BLUE, ORANGE, PANEL, BORDER, TEXT, MUTED
)


def _init_legs(n):
    for i in range(n):
        k = f"leg{i}"
        st.session_state.setdefault(f"{k}_index",   "NIFTY")
        st.session_state.setdefault(f"{k}_expiry",  "")
        st.session_state.setdefault(f"{k}_strike",  0)
        st.session_state.setdefault(f"{k}_type",    "CE")
        st.session_state.setdefault(f"{k}_dir",     "Sell")
        st.session_state.setdefault(f"{k}_ratio",   1)


def _leg_inputs(fyers, i: int, chain_cache: dict) -> dict | None:
    """Render inputs for one leg and return config dict or None."""
    st.markdown(f"**Leg {i+1}**")
    c1, c2, c3, c4, c5, c6 = st.columns([1.2, 1.5, 1.2, 0.8, 0.8, 0.6])

    index = c1.selectbox("Index", ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"],
                         key=f"leg{i}_index", label_visibility="collapsed")

    # Load option chain for this index if not cached
    cache_key = f"chain_{index}"
    if cache_key not in chain_cache:
        resp = fetch_option_chain(fyers, index)
        expiries, strikes, chain_map = parse_option_chain(resp, index)
        chain_cache[cache_key] = {"expiries": expiries, "strikes": strikes, "map": chain_map}

    cd = chain_cache[cache_key]
    expiries = cd["expiries"] or [""]
    strikes  = cd["strikes"]  or [0]

    expiry = c2.selectbox("Expiry", expiries, key=f"leg{i}_expiry",
                          label_visibility="collapsed")
    strike_opts = strikes
    default_strike = strike_opts[len(strike_opts)//2] if strike_opts else 0
    strike = c3.selectbox("Strike", strike_opts,
                          index=strike_opts.index(default_strike) if default_strike in strike_opts else 0,
                          key=f"leg{i}_strike", label_visibility="collapsed")
    opt_type = c4.selectbox("Type", ["CE", "PE"], key=f"leg{i}_type",
                             label_visibility="collapsed")
    direction = c5.selectbox("Dir", ["Buy", "Sell"], key=f"leg{i}_dir",
                              label_visibility="collapsed")
    ratio = c6.number_input("Ratio", 1, 10, 1, key=f"leg{i}_ratio",
                             label_visibility="collapsed")

    # LTP
    if expiry and strike:
        sym = build_symbol(index, expiry, strike, opt_type)
        ltp_data = fetch_ltp(fyers, [sym])
        ltp = ltp_data.get(sym, {}).get("ltp", 0)
        lot = LOT_SIZES.get(index, 1)
        st.caption(f"Symbol: `{sym}`  |  LTP: **{ltp:.2f}**  |  Qty: {ratio * lot}")
        return {"index": index, "expiry": expiry, "strike": strike,
                "opt_type": opt_type, "direction": direction,
                "ratio": ratio, "symbol": sym, "ltp": ltp, "lot": lot}
    return None


def _compute_spread_value(legs: list[dict], ltp_map: dict) -> float:
    """Net spread value (sell legs subtract, buy legs add)."""
    total = 0.0
    for leg in legs:
        ltp = ltp_map.get(leg["symbol"], {}).get("ltp", 0)
        sign = -1 if leg["direction"] == "Sell" else 1
        total += sign * ltp * leg["ratio"]
    return total


def _greeks_row(legs: list[dict], spot: float, T: float, r: float = 0.065):
    """Compute and display net Greeks."""
    net = {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    net_iv_list = []
    for leg in legs:
        ltp = leg.get("ltp", 0)
        if ltp > 0 and T > 0:
            iv = implied_volatility(ltp, spot, leg["strike"], T, r, leg["opt_type"])
            g  = bs_greeks(spot, leg["strike"], T, r, iv, leg["opt_type"])
            lot = leg["lot"] * leg["ratio"]
            sign = -1 if leg["direction"] == "Sell" else 1
            for k in net:
                net[k] += sign * g[k] * lot
            if iv > 0:
                net_iv_list.append(iv * 100)

    avg_iv = np.mean(net_iv_list) if net_iv_list else 0
    st.markdown("**Net Greeks**")
    stat_chips_row([
        ("Net Δ",     f"{net['delta']:.2f}", "blue"),
        ("Net Γ",     f"{net['gamma']:.4f}", "text"),
        ("Net Θ",     f"{net['theta']:.2f}", "red"),
        ("Net V",     f"{net['vega']:.2f}",  "green"),
        ("Avg IV%",   f"{avg_iv:.1f}%",      "orange"),
    ])


def _safety_table(fyers, legs: list[dict], rows_above_below: int) -> pd.DataFrame:
    """Build the safety matrix table around current strikes."""
    if not legs:
        return pd.DataFrame()

    interval_per_leg = []
    for leg in legs:
        interval_per_leg.append(500 if leg["index"] == "SENSEX" else 100)

    records = []
    for offset in range(-rows_above_below, rows_above_below + 1):
        row_legs = []
        for j, leg in enumerate(legs):
            adj_strike = leg["strike"] + offset * interval_per_leg[j]
            sym = build_symbol(leg["index"], leg["expiry"], adj_strike, leg["opt_type"])
            row_legs.append({**leg, "strike": adj_strike, "symbol": sym})

        # Fetch LTPs for all symbols in this row
        syms = [l["symbol"] for l in row_legs]
        ltp_data = fetch_ltp(fyers, syms)
        spread_val = _compute_spread_value(row_legs, ltp_data)

        row_dict = {"Row": "BASE" if offset == 0 else f"{'+' if offset > 0 else ''}{offset}",
                    "Spread": round(spread_val, 2)}
        for j, rl in enumerate(row_legs):
            row_dict[f"Leg {j+1} Strike"] = rl["strike"]
        for j, rl in enumerate(row_legs):
            ld = ltp_data.get(rl["symbol"], {})
            row_dict[f"Leg {j+1} LTP"] = round(ld.get("ltp", 0), 2)
            if j == 0:
                row_dict["Bid"] = round(ld.get("bid", 0), 2)
                row_dict["Ask"] = round(ld.get("ask", 0), 2)
        records.append(row_dict)

    return pd.DataFrame(records)


def render(fyers):
    st.header("📊 Spread Chart + Safety Calculator")

    chain_cache = st.session_state.setdefault("chain_cache_t1", {})
    sp_history  = st.session_state.setdefault("sp_history", [])

    # ── Config ──────────────────────────────────────────
    col_n, col_ct, col_tf = st.columns([1, 1.5, 1.5])
    n_legs = col_n.number_input("Legs", 2, 6, st.session_state.get("n_legs_t1", 2), key="n_legs_t1")
    chart_type = col_ct.selectbox("Chart Type", ["Line", "Candlestick"], key="chart_type_t1")
    timeframe  = col_tf.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "1D"], index=1, key="tf_t1")

    st.divider()
    st.markdown("**Configure Legs** — Index | Expiry | Strike | CE/PE | Buy/Sell | Ratio")

    _init_legs(n_legs)
    legs = []
    for i in range(n_legs):
        leg = _leg_inputs(fyers, i, chain_cache)
        if leg:
            legs.append(leg)
        st.divider()

    # ── Charts ──────────────────────────────────────────
    tab_live, tab_hist = st.tabs(["⚡ Live Feed", "📅 Historical Candles"])

    # Live Feed
    with tab_live:
        col_s, col_stop, col_clr = st.columns([1, 1, 1])
        live_on = st.session_state.get("sp_live_on", False)

        if col_s.button("▶ Start", disabled=live_on, use_container_width=True):
            st.session_state["sp_live_on"] = True
            st.rerun()
        if col_stop.button("⏹ Stop", disabled=not live_on, use_container_width=True):
            st.session_state["sp_live_on"] = False
        if col_clr.button("🗑 Clear", use_container_width=True):
            st.session_state["sp_history"] = []
            sp_history = []

        # Status
        if sp_history:
            st.caption(f"Ticks: {len(sp_history)}  |  Last: {sp_history[-1]['ts']}")

        # Chart
        if sp_history:
            df = pd.DataFrame(sp_history)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["ts"], y=df["spread"],
                                     line=dict(color=BLUE, width=2), name="Spread"))
            fig.update_layout(**dark_layout("Live Spread", 360))
            st.plotly_chart(fig, use_container_width=True)

        # One tick per rerun
        if st.session_state.get("sp_live_on") and legs:
            all_syms = [l["symbol"] for l in legs]
            ltp_data = fetch_ltp(fyers, all_syms)
            if is_market_closed(ltp_data):
                market_closed_notice()
            val = _compute_spread_value(legs, ltp_data)
            ts  = now_ist()
            st.session_state["sp_history"].append({"ts": ts, "spread": val})
            import time; time.sleep(3)
            st.rerun()

    # Historical Candles
    with tab_hist:
        if not legs:
            st.info("Configure legs above to load candle data.")
        else:
            date_col, _ = st.columns([1.5, 2])
            hist_date = date_col.date_input("Date", value=pd.Timestamp.now().date())

            if st.button("📥 Load Candles"):
                date_str = hist_date.strftime("%Y-%m-%d")
                spread_series = None
                for leg in legs:
                    df_c = fetch_candles(fyers, leg["symbol"], timeframe, date_str, date_str)
                    if df_c.empty:
                        continue
                    sign = -1 if leg["direction"] == "Sell" else 1
                    df_c = df_c.set_index("datetime") * sign * leg["ratio"]
                    spread_series = df_c if spread_series is None else spread_series.add(df_c, fill_value=0)

                if spread_series is not None and not spread_series.empty:
                    spread_series = spread_series.reset_index()
                    fig = go.Figure()
                    if chart_type == "Candlestick":
                        fig.add_trace(go.Candlestick(
                            x=spread_series["datetime"],
                            open=spread_series["open"],
                            high=spread_series["high"],
                            low=spread_series["low"],
                            close=spread_series["close"],
                            increasing_line_color=GREEN,
                            decreasing_line_color=RED,
                        ))
                    else:
                        fig.add_trace(go.Scatter(x=spread_series["datetime"],
                                                 y=spread_series["close"],
                                                 line=dict(color=BLUE)))
                    fig.update_layout(**dark_layout(f"Spread — {hist_date}", 380))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("No candle data available. Market may be closed or data unavailable.")

    # ── Summary chips ──────────────────────────────────
    if legs:
        all_syms = [l["symbol"] for l in legs]
        ltp_data = fetch_ltp(fyers, all_syms)
        if is_market_closed(ltp_data):
            market_closed_notice()

        spread_val  = _compute_spread_value(legs, ltp_data)
        net_premium = sum(
            l["ltp"] * l["ratio"] * l["lot"] * (-1 if l["direction"] == "Sell" else 1)
            for l in legs
        )

        st.divider()
        st.markdown("**Summary**")
        stat_chips_row([
            ("SPREAD",    f"{spread_val:.2f}", "blue"),
            ("NET PREMIUM", f"₹{net_premium:,.0f}", "green" if net_premium > 0 else "red"),
        ])

        # Greeks toggle
        if st.checkbox("Show Net Greeks"):
            spot = 0
            try:
                from fyers_data import fetch_spot
                spot = fetch_spot(fyers, legs[0]["index"])
            except Exception:
                pass
            T = 7 / 365  # approximate 1 week
            _greeks_row(legs, spot or legs[0]["strike"], T)

    # ── Safety Calculator ──────────────────────────────
    st.divider()
    st.markdown("### 🛡️ Safety Calculator")

    sc1, sc2 = st.columns([1, 1])
    rows_ab = sc2.slider("Rows ± (above/below)", 1, 10, 3)

    if legs and st.button("🔄 Fetch Safety Matrix"):
        with st.spinner("Fetching…"):
            df_safe = _safety_table(fyers, legs, rows_ab)

        if not df_safe.empty:
            # Highlight base row
            def highlight_base(row):
                if row["Row"] == "BASE":
                    return [f"background-color: #162040; color: {TEXT}"] * len(row)
                return [""] * len(row)

            st.dataframe(df_safe.style.apply(highlight_base, axis=1), use_container_width=True)

            # Export Excel
            buf = BytesIO()
            df_safe.to_excel(buf, index=False)
            st.download_button("📥 Export Excel", buf.getvalue(),
                               file_name="safety_matrix.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
