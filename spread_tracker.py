"""spread_tracker.py — Tab 4: multi-spread live safety tracker.

Each spread is a 2-leg diagonal: LEG 1 = Buy (long, Buy Expiry / Strike 1),
LEG 2 = Sell (short, Sell Expiry / Strike 2). Both share CE/PE.
"""

from __future__ import annotations

import streamlit as st

import styles
import fyers_client as fc
from spread_chart import INDICES, _expiries, _strikes

P = styles.PALETTE


def _spread_legs(cfg, off):
    """Return the two shifted leg dicts for a given ladder offset."""
    iv = int(cfg["interval"])
    leg1 = {"index": cfg["idx"], "expiry": cfg["buy_exp"],
            "strike": int(cfg["strike1"]) + off * iv,
            "opt_type": cfg["ot"], "side": "Buy", "ratio": 1}
    leg2 = {"index": cfg["idx"], "expiry": cfg["sell_exp"],
            "strike": int(cfg["strike2"]) + off * iv,
            "opt_type": cfg["ot"], "side": "Sell", "ratio": 1}
    return leg1, leg2


def _net(qa, qb, field_long, field_short):
    return qa.get(field_long, 0.0) - qb.get(field_short, 0.0)


def _spread_config(i):
    with st.expander(f"Spread {i+1}", expanded=(i == 0)):
        c = st.columns([1, 0.8, 1.4, 1.4])
        idx = c[0].selectbox("Index", INDICES, key=f"tr{i}_idx")
        ot = c[1].selectbox("CE/PE", ["CE", "PE"], key=f"tr{i}_ot")
        exps = _expiries(idx)
        buy_exp = c[2].selectbox("Buy Expiry (long)", exps or ["—"], key=f"tr{i}_be")
        sell_exp = c[3].selectbox("Sell Expiry (short)", exps or ["—"],
                                  key=f"tr{i}_se")
        strikes = _strikes(idx, buy_exp if exps else "")
        c2 = st.columns([1, 1, 1, 1])
        strike1 = c2[0].selectbox("Strike 1", strikes or [0], key=f"tr{i}_s1",
                                  index=len(strikes) // 2 if strikes else 0)
        strike2 = c2[1].selectbox("Strike 2", strikes or [0], key=f"tr{i}_s2",
                                  index=len(strikes) // 2 if strikes else 0)
        interval = c2[2].number_input("Strike Interval", 1, 5000,
                                      fc.STRIKE_INTERVAL.get(idx, 100),
                                      key=f"tr{i}_int")
        rows = c2[3].number_input("Safety Rows ±", 1, 5, 3, key=f"tr{i}_rows")
    return {"idx": idx, "ot": ot, "buy_exp": buy_exp if exps else "",
            "sell_exp": sell_exp if exps else "", "strike1": strike1,
            "strike2": strike2, "interval": interval, "rows": int(rows)}


def _render_spread_table(cfg, quotes, show_greeks):
    if not (cfg["buy_exp"] and cfg["sell_exp"]):
        st.info("Incomplete spread — pick expiries.")
        return
    rows_n = cfg["rows"]
    greek_h = "<th style='padding:6px 8px;'>Δ NET</th>" if show_greeks else ""
    head = ("<th style='padding:6px 8px;text-align:left;'>SERIES</th>"
            "<th style='padding:6px 8px;'>LEG 1</th>"
            "<th style='padding:6px 8px;'>LEG 2</th>"
            "<th style='padding:6px 8px;'>BID</th>"
            "<th style='padding:6px 8px;'>ASK</th>"
            "<th style='padding:6px 8px;'>LTP</th>"
            "<th style='padding:6px 8px;'>PREV</th>"
            "<th style='padding:6px 8px;'>HIGH/LOW</th>" + greek_h)
    body = []
    under = None
    if show_greeks:
        try:
            under = fc.underlying_ltp(cfg["idx"])
        except Exception:
            under = 0.0
    for off in range(rows_n, -rows_n - 1, -1):
        leg1, leg2 = _spread_legs(cfg, off)
        s1, s2 = fc.leg_to_symbol(leg1), fc.leg_to_symbol(leg2)
        qa, qb = quotes.get(s1, {}), quotes.get(s2, {})
        ltp = qa.get("ltp", 0.0) - qb.get("ltp", 0.0)
        bid = qa.get("bid", 0.0) - qb.get("ask", 0.0)
        ask = qa.get("ask", 0.0) - qb.get("bid", 0.0)
        prev = qa.get("prev_close", 0.0) - qb.get("prev_close", 0.0)
        hi = qa.get("high", 0.0) - qb.get("low", 0.0)
        lo = qa.get("low", 0.0) - qb.get("high", 0.0)
        label = "BASE" if off == 0 else (f"+{off}" if off > 0 else f"{off}")
        bg = P["BLUE"] if off == 0 else "transparent"
        tc = "#fff" if off == 0 else P["TEXT"]
        fw = "700" if off == 0 else "400"
        greek_c = ""
        if show_greeks and under:
            d = 0.0
            for lg, sgn in ((leg1, 1), (leg2, -1)):
                e = fc.find_expiry(cfg["idx"], lg["expiry"])
                if not e:
                    continue
                t = fc.years_to_expiry(e["date"])
                q = quotes.get(fc.leg_to_symbol(lg), {})
                iv = fc.implied_vol(q.get("ltp", 0.0), under,
                                    float(lg["strike"]), t, lg["opt_type"])
                if iv:
                    d += sgn * fc.bs_greeks(under, float(lg["strike"]), t, iv,
                                            lg["opt_type"])["delta"]
            greek_c = (f"<td style='padding:6px 8px;text-align:right;color:{tc};'>"
                       f"{d:,.3f}</td>")
        body.append(
            f"<tr style='background:{bg};border-bottom:1px solid {P['BORDER']};'>"
            f"<td style='padding:6px 8px;color:{tc};font-weight:{fw};'>{label}</td>"
            f"<td style='padding:6px 8px;text-align:center;color:{tc};'>{leg1['strike']}</td>"
            f"<td style='padding:6px 8px;text-align:center;color:{tc};'>{leg2['strike']}</td>"
            f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{bid:,.2f}</td>"
            f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{ask:,.2f}</td>"
            f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{ltp:,.2f}</td>"
            f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{prev:,.2f}</td>"
            f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{hi:,.1f}/{lo:,.1f}</td>"
            f"{greek_c}</tr>")
    table = (f"<div style='overflow-x:auto;margin-bottom:10px;'><table style='width:100%;"
             f"border-collapse:collapse;background:{P['PANEL']};border:1px solid "
             f"{P['BORDER']};border-radius:6px;font-size:12px;color:{P['TEXT']};'>"
             f"<thead><tr style='color:{P['MUTED']};border-bottom:2px solid "
             f"{P['ORANGE']};'>{head}</tr></thead><tbody>"
             + "".join(body) + "</tbody></table></div>")
    st.markdown(table, unsafe_allow_html=True)


def render(user):
    top = st.columns([1, 1, 2])
    n = top[0].number_input("Number of Spreads", 1, 10, 1, key="tr_n")
    show_greeks = top[1].checkbox("Greeks per row", key="tr_greeks")
    fetch = top[2].button("🔄 Fetch All", key="tr_fetch")

    cfgs = [_spread_config(i) for i in range(int(n))]
    st.session_state["tracker_cfgs"] = cfgs

    if fetch:
        # one batched quote across every symbol of every spread + ladder row
        syms = set()
        for cfg in cfgs:
            if not (cfg["buy_exp"] and cfg["sell_exp"]):
                continue
            for off in range(-cfg["rows"], cfg["rows"] + 1):
                l1, l2 = _spread_legs(cfg, off)
                syms.add(fc.leg_to_symbol(l1))
                syms.add(fc.leg_to_symbol(l2))
        try:
            quotes = fc.get_quotes(list(syms))
        except Exception as e:
            st.error(f"Quote fetch failed: {e}")
            return
        for i, cfg in enumerate(cfgs):
            st.markdown(styles.section(f"Spread {i+1} · {cfg['idx']} "
                                       f"{cfg['ot']} ladder"), unsafe_allow_html=True)
            _render_spread_table(cfg, quotes, show_greeks)
    else:
        st.caption("Configure spreads above, then press **Fetch All**.")
