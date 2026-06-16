"""
Tab 4 — Spread Tracker (1–10 calendar/diagonal spreads)
"""

import streamlit as st
import pandas as pd
from fyers_data import (
    fetch_option_chain, parse_option_chain, build_symbol,
    fetch_ltp, LOT_SIZES
)
from ui_utils import dark_layout, ROW_BASE, TEXT, PANEL, BORDER


def _tracker_config(fyers, idx: int, chain_cache: dict) -> dict:
    """Render config UI for one spread and return config dict."""
    with st.expander(f"Spread {idx+1}", expanded=idx == 0):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        index    = c1.selectbox("Index", ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"],
                                key=f"tr_index_{idx}")
        opt_type = c2.selectbox("CE/PE", ["CE", "PE"], key=f"tr_ot_{idx}")

        ck = f"chain_{index}"
        if ck not in chain_cache:
            resp = fetch_option_chain(fyers, index)
            expiries, strikes, _ = parse_option_chain(resp, index)
            chain_cache[ck] = {"expiries": expiries, "strikes": strikes}

        cd = chain_cache.get(ck, {})
        expiries = cd.get("expiries", [""])
        strikes  = cd.get("strikes", [0])

        buy_exp  = c3.selectbox("Buy Expiry",  expiries, key=f"tr_buy_exp_{idx}")
        sell_exp = c4.selectbox("Sell Expiry", expiries, key=f"tr_sell_exp_{idx}")

        c5, c6, c7, c8 = st.columns(4)
        mid = len(strikes) // 2
        strike1 = c5.selectbox("Strike 1", strikes, index=mid, key=f"tr_str1_{idx}")
        strike2 = c6.selectbox("Strike 2", strikes, index=mid, key=f"tr_str2_{idx}")
        interval = c7.number_input("Interval", 50, 1000,
                                   500 if index == "SENSEX" else 100,
                                   step=50, key=f"tr_int_{idx}")
        s_rows = c8.number_input("Safety Rows", 1, 5, 2, key=f"tr_rows_{idx}")

        return {
            "index": index, "opt_type": opt_type,
            "buy_exp": buy_exp, "sell_exp": sell_exp,
            "strike1": strike1, "strike2": strike2,
            "interval": interval, "safety_rows": int(s_rows),
        }


def _build_spread_table(fyers, cfg: dict) -> pd.DataFrame:
    """Build spread table with safety rows."""
    index    = cfg["index"]
    ot       = cfg["opt_type"]
    buy_exp  = cfg["buy_exp"]
    sell_exp = cfg["sell_exp"]
    s1       = cfg["strike1"]
    s2       = cfg["strike2"]
    interval = cfg["interval"]
    s_rows   = cfg["safety_rows"]

    records = []
    for offset in range(-s_rows, s_rows + 1):
        adj_s1 = s1 + offset * interval
        adj_s2 = s2 + offset * interval

        sym_buy  = build_symbol(index, buy_exp,  adj_s1, ot)
        sym_sell = build_symbol(index, sell_exp, adj_s2, ot)

        syms = [sym_buy, sym_sell]
        ltp_data = fetch_ltp(fyers, syms)

        buy_d  = ltp_data.get(sym_buy, {})
        sell_d = ltp_data.get(sym_sell, {})

        spread_ltp  = buy_d.get("ltp", 0) - sell_d.get("ltp", 0)
        spread_bid  = buy_d.get("bid", 0) - sell_d.get("ask", 0)
        spread_ask  = buy_d.get("ask", 0) - sell_d.get("bid", 0)

        records.append({
            "Series":      "BASE" if offset == 0 else f"{'+' if offset > 0 else ''}{offset}",
            f"Leg 1 ({ot})": adj_s1,
            f"Leg 2 ({ot})": adj_s2,
            "Buy LTP":     round(buy_d.get("ltp", 0), 2),
            "Sell LTP":    round(sell_d.get("ltp", 0), 2),
            "Spread LTP":  round(spread_ltp, 2),
            "Spread Bid":  round(spread_bid, 2),
            "Spread Ask":  round(spread_ask, 2),
            "Buy Prev":    round(buy_d.get("prev_close", 0), 2),
            "Sell Prev":   round(sell_d.get("prev_close", 0), 2),
        })

    return pd.DataFrame(records)


def render(fyers):
    st.header("🔍 Spread Tracker")

    chain_cache = st.session_state.setdefault("chain_cache_t4", {})

    n_spreads = st.number_input("Number of Spreads", 1, 10, 2, key="n_spreads_t4")

    configs = []
    for i in range(n_spreads):
        cfg = _tracker_config(fyers, i, chain_cache)
        configs.append(cfg)

    show_greeks = st.checkbox("Show Net Greeks", key="tr_greeks")

    if st.button("🔄 Fetch All Spreads", use_container_width=True):
        for i, cfg in enumerate(configs):
            st.subheader(f"Spread {i+1} — {cfg['index']} {cfg['opt_type']}")
            with st.spinner(f"Loading spread {i+1}…"):
                df = _build_spread_table(fyers, cfg)

            def highlight_base(row):
                if row["Series"] == "BASE":
                    return [f"background-color: {ROW_BASE}"] * len(row)
                return [""] * len(row)

            st.dataframe(df.style.apply(highlight_base, axis=1), use_container_width=True)
