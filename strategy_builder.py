"""strategy_builder.py — Tab 7: multi-leg strategy builder with presets."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import styles
import fyers_client as fc
from spread_chart import INDICES, _expiries, _strikes, _nearest_index

P = styles.PALETTE
_LCOLS = ["Index", "Expiry", "Side", "Type", "Strike", "Lots", "Premium"]

PRESETS = ["Custom", "Bull Call Spread", "Bear Put Spread", "Long Straddle",
           "Short Straddle", "Long Strangle", "Short Strangle", "Iron Condor",
           "Bull Put Spread", "Bear Call Spread", "Long Butterfly"]


def _leg(index, expiry, side, otype, strike, lots=1, prem=0.0):
    return {"Index": index, "Expiry": expiry, "Side": side, "Type": otype,
            "Strike": int(strike), "Lots": int(lots), "Premium": float(prem)}


def preset_legs(name, atm, wing, index, expiry):
    w = int(wing)
    f = lambda s, o, k, l=1: _leg(index, expiry, s, o, k, l)
    if name == "Bull Call Spread":
        return [f("Buy", "CE", atm), f("Sell", "CE", atm + w)]
    if name == "Bear Put Spread":
        return [f("Buy", "PE", atm), f("Sell", "PE", atm - w)]
    if name == "Long Straddle":
        return [f("Buy", "CE", atm), f("Buy", "PE", atm)]
    if name == "Short Straddle":
        return [f("Sell", "CE", atm), f("Sell", "PE", atm)]
    if name == "Long Strangle":
        return [f("Buy", "CE", atm + w), f("Buy", "PE", atm - w)]
    if name == "Short Strangle":
        return [f("Sell", "CE", atm + w), f("Sell", "PE", atm - w)]
    if name == "Iron Condor":
        return [f("Sell", "CE", atm + w), f("Buy", "CE", atm + 2 * w),
                f("Sell", "PE", atm - w), f("Buy", "PE", atm - 2 * w)]
    if name == "Bull Put Spread":
        return [f("Sell", "PE", atm), f("Buy", "PE", atm - w)]
    if name == "Bear Call Spread":
        return [f("Sell", "CE", atm), f("Buy", "CE", atm + w)]
    if name == "Long Butterfly":
        return [f("Buy", "CE", atm - w), f("Sell", "CE", atm, 2),
                f("Buy", "CE", atm + w)]
    return []


def _atm_strike(index, expiry):
    strikes = _strikes(index, expiry)
    if not strikes:
        return 0
    try:
        spot = fc.underlying_ltp(index)
    except Exception:
        spot = 0
    if spot <= 0:
        return strikes[len(strikes) // 2]
    return strikes[_nearest_index(strikes, spot)]


def render(user):
    st.markdown(styles.section("Preset"), unsafe_allow_html=True)
    c = st.columns([1.4, 1, 1.4, 1, 1])
    preset = c[0].selectbox("Strategy", PRESETS, key="sb_preset")
    base_idx = c[1].selectbox("Base Index", INDICES, key="sb_idx")
    exps = _expiries(base_idx)
    base_exp = c[2].selectbox("Base Expiry", exps or ["—"], key="sb_exp")
    wing = c[3].number_input("Wing (pts)", 50, 5000,
                             fc.STRIKE_INTERVAL.get(base_idx, 100) * 2,
                             step=fc.STRIKE_INTERVAL.get(base_idx, 100),
                             key="sb_wing")
    if c[4].button("⚙️ Load", key="sb_load") and preset != "Custom":
        if not exps:
            st.warning("No expiry data yet.")
        else:
            atm = _atm_strike(base_idx, base_exp)
            recs = preset_legs(preset, atm, wing, base_idx, base_exp)
            if recs:
                st.session_state["sb_records"] = recs
                st.rerun()

    st.markdown(styles.section("Legs"), unsafe_allow_html=True)
    base = st.session_state.get("sb_records")
    df_in = pd.DataFrame(base) if base else pd.DataFrame([
        _leg(base_idx, base_exp if exps else "", "Buy", "CE",
             _atm_strike(base_idx, base_exp) if exps else 0)])
    for col in _LCOLS:
        if col not in df_in.columns:
            df_in[col] = "" if col == "Expiry" else 0
    df_in = df_in[_LCOLS]

    edited = st.data_editor(
        df_in, num_rows="dynamic", use_container_width=True, key="sb_editor",
        column_config={
            "Index": st.column_config.SelectboxColumn(options=INDICES),
            "Side": st.column_config.SelectboxColumn(options=["Buy", "Sell"]),
            "Type": st.column_config.SelectboxColumn(options=["CE", "PE"]),
            "Strike": st.column_config.NumberColumn(format="%d"),
            "Lots": st.column_config.NumberColumn(min_value=1, format="%d"),
            "Premium": st.column_config.NumberColumn(format="%.2f"),
        })
    st.session_state["strategy_records"] = edited.to_dict("records")
    st.session_state["sb_records"] = edited.to_dict("records")

    cc = st.columns([1, 1, 3])
    if cc[0].button("💲 Fetch Premiums", key="sb_fetch"):
        _fill_premiums(edited)
        st.rerun()
    analyze = cc[1].button("📈 Analyze", key="sb_analyze")

    if analyze:
        _analyze(edited)


def _legs_from(edited):
    out = []
    for r in edited.to_dict("records"):
        if not str(r.get("Expiry")).strip() or float(r.get("Strike") or 0) <= 0:
            continue
        out.append({"index": r["Index"], "expiry": str(r["Expiry"]).strip(),
                    "side": r["Side"], "opt_type": r["Type"],
                    "strike": int(float(r["Strike"])),
                    "lots": int(float(r["Lots"] or 1)),
                    "premium": float(r["Premium"] or 0.0)})
    return out


def _fill_premiums(edited):
    legs = _legs_from(edited)
    if not legs:
        return
    syms = [fc.leg_to_symbol(lg) for lg in legs]
    try:
        quotes = fc.get_quotes(syms)
    except Exception as e:
        st.error(f"Quote fetch failed: {e}")
        return
    recs = st.session_state.get("sb_records", [])
    li = 0
    for r in recs:
        if not str(r.get("Expiry")).strip() or float(r.get("Strike") or 0) <= 0:
            continue
        sym = syms[li]
        r["Premium"] = round(quotes.get(sym, {}).get("ltp", 0.0), 2)
        li += 1
    st.session_state["sb_records"] = recs


def _analyze(edited):
    legs = _legs_from(edited)
    if not legs:
        st.warning("Add at least one valid leg (expiry + strike).")
        return
    syms = [fc.leg_to_symbol(lg) for lg in legs]
    try:
        quotes = fc.get_quotes(syms)
    except Exception:
        quotes = {}

    dom = legs[0]["index"]
    try:
        spot0 = fc.underlying_ltp(dom)
    except Exception:
        spot0 = 0.0
    if spot0 <= 0:
        spot0 = float(legs[0]["strike"])

    # payoff legs in rupees
    plegs, summary = [], []
    net_g = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    net_prem_rupees = 0.0
    for lg, sym in zip(legs, syms):
        lot = fc.get_lot_size(lg["index"], sym)
        qty = lg["lots"] * lot
        sign = 1.0 if lg["side"] == "Buy" else -1.0
        plegs.append({"opt_type": lg["opt_type"], "strike": float(lg["strike"]),
                      "side": lg["side"], "qty": qty, "premium": lg["premium"]})
        net_prem_rupees += sign * lg["premium"] * qty
        # greeks + IV
        e = fc.find_expiry(lg["index"], lg["expiry"])
        iv_pct, delta = 0.0, 0.0
        if e and spot0 > 0:
            t = fc.years_to_expiry(e["date"])
            iv = fc.implied_vol(lg["premium"], spot0, float(lg["strike"]),
                                t, lg["opt_type"])
            if iv:
                iv_pct = iv * 100
                g = fc.bs_greeks(spot0, float(lg["strike"]), t, iv, lg["opt_type"])
                delta = g["delta"]
                for k in net_g:
                    net_g[k] += sign * qty * g[k]
        summary.append({
            "Leg": f"{lg['side']} {lg['lots']}× {lg['index']} "
                   f"{lg['strike']}{lg['opt_type']}",
            "Strike": lg["strike"], "Lots": lg["lots"], "Lot Size": lot,
            "Premium": round(lg["premium"], 2), "IV %": round(iv_pct, 2),
            "Delta": round(delta, 3)})

    lo, hi = spot0 * 0.8, spot0 * 1.2
    spots = [lo + (hi - lo) * k / 240 for k in range(241)]
    pnl = fc.payoff_curve(plegs, spots)
    mx, mn, bes = fc.payoff_stats(spots, pnl)
    mp, ml = f"₹{mx:,.0f}", f"₹{mn:,.0f}"
    if len(pnl) >= 2:
        if pnl[-1] - pnl[-2] > 1e-6:
            mp = "Unlimited"
        if pnl[-1] - pnl[-2] < -1e-6:
            ml = "Unlimited"
    be_txt = ", ".join(f"{b:,.0f}" for b in bes) if bes else "—"
    np_color = P["RED"] if net_prem_rupees >= 0 else P["GREEN"]

    st.markdown(styles.chips_row([
        ("Net Premium ₹", f"{net_prem_rupees:,.0f}", np_color),
        ("Max Profit", mp, P["GREEN"]),
        ("Max Loss", ml, P["RED"]),
        ("Breakevens", be_txt, P["ORANGE"]),
    ]), unsafe_allow_html=True)

    # payoff chart
    pos = [v if v >= 0 else None for v in pnl]
    neg = [v if v < 0 else None for v in pnl]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=spots, y=pos, mode="lines", name="Profit",
                             line=dict(color=P["GREEN"], width=2)))
    fig.add_trace(go.Scatter(x=spots, y=neg, mode="lines", name="Loss",
                             line=dict(color=P["RED"], width=2)))
    for b in bes:
        fig.add_vline(x=b, line_dash="dash", line_color=P["ORANGE"])
    fig.add_vline(x=spot0, line_dash="dash", line_color=P["MUTED"],
                  annotation_text=f"Spot {spot0:,.0f}")
    fig.update_layout(**styles.plotly_layout(f"{dom} payoff at expiry (₹)", 440))
    st.plotly_chart(fig, use_container_width=True, key="sb_payoff")

    st.markdown(styles.section("Net Greeks"), unsafe_allow_html=True)
    st.markdown(styles.chips_row([
        ("Net Delta", f"{net_g['delta']:,.1f}", P["BLUE"]),
        ("Net Gamma", f"{net_g['gamma']:,.4f}", P["GREEN"]),
        ("Net Vega", f"{net_g['vega']:,.0f}", P["PURPLE"]),
        ("Net Theta ₹/day", f"{net_g['theta']:,.0f}", P["RED"]),
    ]), unsafe_allow_html=True)

    # P&L simulation -10%..+10%
    st.markdown(styles.section("P&L simulation (spot move)"),
                unsafe_allow_html=True)
    sim = []
    for pct in range(-10, 11, 2):
        s = spot0 * (1 + pct / 100)
        sim.append({"Spot Move %": f"{pct:+d}%", "Spot": round(s, 0),
                    "P&L ₹": round(fc.payoff_at(plegs, s), 0)})
    st.dataframe(pd.DataFrame(sim), use_container_width=True, hide_index=True)

    st.markdown(styles.section("Leg summary"), unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
