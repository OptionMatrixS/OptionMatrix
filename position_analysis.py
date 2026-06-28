"""position_analysis.py — Tab 6: live position P&L, Greeks, and payoff.

P&L is shown step-by-step in rupees: (LTP - entry) x lot_size x lots x sign.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import styles
import fyers_client as fc
from spread_chart import INDICES

P = styles.PALETTE

_COLS = ["Index", "Expiry", "Strike", "Type", "Side", "Lots", "Entry"]


def _starter_df():
    return pd.DataFrame([
        {"Index": "NIFTY", "Expiry": "", "Strike": 0, "Type": "CE",
         "Side": "Buy", "Lots": 1, "Entry": 0.0},
    ])


def _expiry_choices(index):
    try:
        return fc.expiry_labels(index)
    except Exception:
        return []


def render(user):
    st.markdown(styles.section("Positions"), unsafe_allow_html=True)
    st.caption("Add your open option legs. Expiry must match a live Fyers label "
               "(e.g. '19 MAY 26 (W)'). Entry = your fill price in points.")

    base = st.session_state.get("cfg_positions_records")
    df_in = pd.DataFrame(base) if base else _starter_df()
    for col in _COLS:
        if col not in df_in.columns:
            df_in[col] = "" if col in ("Expiry",) else 0
    df_in = df_in[_COLS]

    edited = st.data_editor(
        df_in, num_rows="dynamic", use_container_width=True, key="pos_editor",
        column_config={
            "Index": st.column_config.SelectboxColumn(options=INDICES),
            "Type": st.column_config.SelectboxColumn(options=["CE", "PE"]),
            "Side": st.column_config.SelectboxColumn(options=["Buy", "Sell"]),
            "Strike": st.column_config.NumberColumn(format="%d"),
            "Lots": st.column_config.NumberColumn(min_value=1, format="%d"),
            "Entry": st.column_config.NumberColumn(format="%.2f"),
        })
    st.session_state["cfg_positions_records"] = edited.to_dict("records")

    if not st.button("📂 Analyze Positions", key="pos_run"):
        return

    rows = [r for r in edited.to_dict("records")
            if str(r.get("Expiry")).strip() and float(r.get("Strike") or 0) > 0]
    if not rows:
        st.warning("Add at least one position with a valid expiry and strike.")
        return

    # Resolve symbols + one batched quote
    legs = []
    for r in rows:
        legs.append({"index": r["Index"], "expiry": str(r["Expiry"]).strip(),
                     "strike": int(float(r["Strike"])), "opt_type": r["Type"],
                     "side": r["Side"], "lots": int(float(r["Lots"] or 1)),
                     "entry": float(r["Entry"] or 0.0)})
    syms = [fc.leg_to_symbol(lg) for lg in legs]
    try:
        quotes = fc.get_quotes(syms)
    except Exception as e:
        st.error(f"Quote fetch failed: {e}")
        return

    under_cache = {}
    breakdown = []
    net_pnl = 0.0
    net_g = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    for lg, sym in zip(legs, syms):
        idx = lg["index"]
        lot = fc.get_lot_size(idx, sym)
        ltp = quotes.get(sym, {}).get("ltp", 0.0)
        sign = fc.leg_sign(lg)
        qty = lg["lots"] * lot
        pts = ltp - lg["entry"]
        pnl = sign * pts * qty
        net_pnl += pnl
        breakdown.append({
            "Position": f"{lg['side']} {lg['lots']}× {idx} {lg['strike']}{lg['opt_type']}",
            "Entry": round(lg["entry"], 2), "LTP": round(ltp, 2),
            "Δ Points": round(pts, 2), "Lot": lot, "Qty": qty,
            "P&L ₹": round(pnl, 2)})
        # Greeks
        if idx not in under_cache:
            try:
                under_cache[idx] = fc.underlying_ltp(idx)
            except Exception:
                under_cache[idx] = 0.0
        spot = under_cache[idx]
        e = fc.find_expiry(idx, lg["expiry"])
        if e and spot > 0:
            t = fc.years_to_expiry(e["date"])
            iv = fc.implied_vol(ltp, spot, float(lg["strike"]), t, lg["opt_type"])
            if iv:
                g = fc.bs_greeks(spot, float(lg["strike"]), t, iv, lg["opt_type"])
                for k in net_g:
                    net_g[k] += sign * qty * g[k]

    pnl_color = P["GREEN"] if net_pnl >= 0 else P["RED"]
    st.markdown(styles.chips_row([
        ("Net P&L ₹", f"{net_pnl:,.0f}", pnl_color),
        ("Net Delta", f"{net_g['delta']:,.1f}", P["BLUE"]),
        ("Net Gamma", f"{net_g['gamma']:,.4f}", P["GREEN"]),
        ("Net Vega", f"{net_g['vega']:,.0f}", P["PURPLE"]),
        ("Net Theta ₹/day", f"{net_g['theta']:,.0f}", P["RED"]),
    ]), unsafe_allow_html=True)

    st.markdown(styles.section("P&L breakdown (step-by-step)"),
                unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(breakdown), use_container_width=True, hide_index=True)

    # Payoff at expiry for the dominant index only (mixing indices on one spot
    # axis would be meaningless).
    dom = Counter(lg["index"] for lg in legs).most_common(1)[0][0]
    dom_legs = []
    for lg, sym in zip(legs, syms):
        if lg["index"] != dom:
            continue
        lot = fc.get_lot_size(dom, sym)
        dom_legs.append({"opt_type": lg["opt_type"], "strike": float(lg["strike"]),
                         "side": lg["side"], "qty": lg["lots"] * lot,
                         "premium": lg["entry"]})
    spot0 = under_cache.get(dom, 0.0) or float(dom_legs[0]["strike"])
    lo, hi = spot0 * 0.8, spot0 * 1.2
    spots = [lo + (hi - lo) * k / 200 for k in range(201)]
    pnl = fc.payoff_curve(dom_legs, spots)
    pos = [v if v >= 0 else None for v in pnl]
    neg = [v if v < 0 else None for v in pnl]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=spots, y=pos, mode="lines", name="Profit",
                             line=dict(color=P["GREEN"], width=2)))
    fig.add_trace(go.Scatter(x=spots, y=neg, mode="lines", name="Loss",
                             line=dict(color=P["RED"], width=2)))
    fig.add_vline(x=spot0, line_dash="dash", line_color=P["MUTED"],
                  annotation_text=f"Spot {spot0:,.0f}")
    fig.update_layout(**styles.plotly_layout(f"{dom} payoff at expiry (₹)", 420))
    st.plotly_chart(fig, use_container_width=True, key="pos_payoff")
    if len(set(lg["index"] for lg in legs)) > 1:
        st.caption(f"Payoff shown for {dom} legs only (positions span multiple "
                   f"indices).")
