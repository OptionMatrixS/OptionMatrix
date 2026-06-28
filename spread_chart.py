"""spread_chart.py — Tab 1: Spread Chart + embedded Safety Calculator."""

from __future__ import annotations

import io
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import styles
import fyers_client as fc

INDICES = ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"]
REFRESH_INTERVAL = 3  # seconds between live ticks
P = styles.PALETTE


# --- safe network wrappers -------------------------------------------------
def _expiries(index):
    try:
        return fc.expiry_labels(index)
    except Exception as e:
        st.session_state["_fy_err"] = str(e)
        return []


def _strikes(index, label):
    if not label:
        return []
    try:
        return fc.get_strikes(index, label)
    except Exception as e:
        st.session_state["_fy_err"] = str(e)
        return []


def _nearest_index(options, target):
    if not options:
        return 0
    try:
        return min(range(len(options)), key=lambda i: abs(float(options[i]) - target))
    except Exception:
        return len(options) // 2


# --- leg builder -----------------------------------------------------------
def build_legs(prefix: str, n_legs: int):
    legs = []
    for i in range(n_legs):
        st.markdown(styles.leg_header(i + 1), unsafe_allow_html=True)
        c = st.columns([1.2, 1.7, 1.3, 0.9, 0.9, 0.8])
        idx = c[0].selectbox("Index", INDICES, key=f"{prefix}_l{i}_idx",
                             label_visibility="collapsed")
        exps = _expiries(idx)
        exp = c[1].selectbox("Expiry", exps or ["—"], key=f"{prefix}_l{i}_exp",
                             label_visibility="collapsed")
        strikes = _strikes(idx, exp if exps else "")
        strike = c[2].selectbox(
            "Strike", strikes or [0], key=f"{prefix}_l{i}_stk",
            index=(len(strikes) // 2 if strikes else 0),
            label_visibility="collapsed")
        ot = c[3].selectbox("Type", ["CE", "PE"], key=f"{prefix}_l{i}_ot",
                            label_visibility="collapsed")
        side = c[4].selectbox("Side", ["Buy", "Sell"], key=f"{prefix}_l{i}_side",
                              label_visibility="collapsed")
        ratio = c[5].number_input("Ratio", 1, 10, 1, key=f"{prefix}_l{i}_ratio",
                                  label_visibility="collapsed")
        legs.append({"index": idx, "expiry": exp if exps else "",
                     "strike": strike, "opt_type": ot, "side": side,
                     "ratio": int(ratio)})
    return legs


def valid_legs(legs):
    return [lg for lg in legs if lg.get("expiry") and lg.get("strike")]


# --- live quote table + spread ---------------------------------------------
def quote_table(legs):
    syms = [fc.leg_to_symbol(lg) for lg in legs]
    quotes = fc.get_quotes(syms)
    rows = []
    net = 0.0
    for lg, sym in zip(legs, syms):
        ltp = quotes.get(sym, {}).get("ltp", 0.0)
        contrib = fc.leg_sign(lg) * lg["ratio"] * ltp
        net += contrib
        rows.append({"Leg": f"{lg['side']} {lg['ratio']}× {lg['index']} "
                            f"{lg['strike']}{lg['opt_type']}",
                     "Symbol": sym, "LTP": round(ltp, 2),
                     "Net": round(contrib, 2)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return quotes, net


# --- Greeks ----------------------------------------------------------------
def net_greeks(legs, quotes):
    under = {}
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    ivs = []
    for lg in legs:
        idx = lg["index"]
        if idx not in under:
            try:
                under[idx] = fc.underlying_ltp(idx)
            except Exception:
                under[idx] = 0.0
        spot = under[idx]
        e = fc.find_expiry(idx, lg["expiry"])
        if not e or spot <= 0:
            continue
        t = fc.years_to_expiry(e["date"])
        sym = fc.leg_to_symbol(lg)
        ltp = quotes.get(sym, {}).get("ltp", 0.0)
        iv = fc.implied_vol(ltp, spot, float(lg["strike"]), t, lg["opt_type"])
        if not iv:
            continue
        ivs.append(iv)
        g = fc.bs_greeks(spot, float(lg["strike"]), t, iv, lg["opt_type"])
        sgn = fc.leg_sign(lg) * lg["ratio"]
        for k in net:
            net[k] += sgn * g[k]
    avg_iv = (sum(ivs) / len(ivs) * 100) if ivs else 0.0
    return net, avg_iv


# --- summary chips ---------------------------------------------------------
def summary_chips(legs, quotes, spread_val):
    # payoff legs use LTP as entry premium, qty = ratio (points basis)
    plegs, idx0 = [], legs[0]["index"] if legs else "NIFTY"
    for lg in legs:
        sym = fc.leg_to_symbol(lg)
        prem = quotes.get(sym, {}).get("ltp", 0.0)
        plegs.append({"opt_type": lg["opt_type"], "strike": float(lg["strike"]),
                      "side": lg["side"], "qty": lg["ratio"], "premium": prem})
    try:
        spot0 = fc.underlying_ltp(idx0)
    except Exception:
        spot0 = 0.0
    if spot0 <= 0 and plegs:
        spot0 = float(legs[0]["strike"])
    lo, hi = spot0 * 0.8, spot0 * 1.2
    spots = [lo + (hi - lo) * k / 200 for k in range(201)] if spot0 > 0 else []
    pnl = fc.payoff_curve(plegs, spots) if spots else []
    mx, mn, bes = fc.payoff_stats(spots, pnl)
    # unlimited detection on the upside
    mp = f"{mx:,.1f}"
    ml = f"{mn:,.1f}"
    if len(pnl) >= 2:
        if pnl[-1] - pnl[-2] > 1e-6:
            mp = "Unlimited"
        if pnl[-1] - pnl[-2] < -1e-6:
            ml = "Unlimited"
    be_txt = ", ".join(f"{b:,.0f}" for b in bes) if bes else "—"
    net_prem = spread_val
    np_color = P["RED"] if net_prem >= 0 else P["GREEN"]  # debit red, credit green
    st.markdown(styles.chips_row([
        ("Spread", f"{spread_val:,.2f}", P["BLUE"]),
        ("Net Premium", f"{net_prem:,.2f}", np_color),
        ("Max Profit", mp, P["GREEN"]),
        ("Max Loss", ml, P["RED"]),
        ("Breakeven", be_txt, P["ORANGE"]),
    ]), unsafe_allow_html=True)


# --- live feed -------------------------------------------------------------
def live_feed(legs):
    vl = valid_legs(legs)
    st.markdown(styles.section("📡 Live Feed (works 24/7 on quotes)"),
                unsafe_allow_html=True)
    c1, c2, c3, _ = st.columns([1, 1, 1, 3])
    if c1.button("▶ Start", key="sp_start"):
        st.session_state["sp_live_on"] = True
        st.session_state["sp_last_tick"] = time.time()
    if c2.button("⏹ Stop", key="sp_stop"):
        st.session_state["sp_live_on"] = False
    if c3.button("🧹 Clear", key="sp_clear"):
        st.session_state["sp_hist"] = []

    hist = st.session_state.setdefault("sp_hist", [])
    on = st.session_state.get("sp_live_on", False)

    cur = None
    if vl:
        try:
            quotes = fc.get_quotes([fc.leg_to_symbol(lg) for lg in vl])
            cur = fc.spread_value(vl, quotes)
        except Exception as e:
            st.warning(f"Quote fetch failed: {e}")

    status = ("🟢 LIVE" if on else "⚪ Idle")
    last_ts = hist[-1][0].strftime("%H:%M:%S") if hist else "—"
    st.markdown(
        f"<span style='color:{P['MUTED']};font-size:12px;'>{status} · "
        f"ticks: {len(hist)} · last: {last_ts} IST</span>", unsafe_allow_html=True)
    if cur is not None:
        st.markdown(f"<div style='font-size:34px;font-weight:700;color:{P['BLUE']};'>"
                    f"{cur:,.2f}</div>", unsafe_allow_html=True)

    if hist:
        xs = [h[0] for h in hist]
        ys = [h[1] for h in hist]
        fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines",
                                   line=dict(color=P["BLUE"], width=2)))
        fig.update_layout(**styles.plotly_layout(height=360))
        st.plotly_chart(fig, use_container_width=True,
                        key=f"sp_live_{len(hist)}")

    if on and vl and cur is not None:
        st.session_state["sp_hist"].append((fc.ist_now(), cur))
        remaining = REFRESH_INTERVAL - (time.time() -
                                        st.session_state.get("sp_last_tick", 0))
        st.session_state["sp_last_tick"] = time.time()
        if remaining > 0:
            time.sleep(remaining)
        st.rerun()


# --- historical candles ----------------------------------------------------
def _spread_candles(legs, dfrom, dto, res):
    merged = None
    for lg in legs:
        df = fc.get_candles(fc.leg_to_symbol(lg), dfrom, dto, res)
        if df.empty:
            return pd.DataFrame()
        s, r = fc.leg_sign(lg), float(lg["ratio"])
        df = df.set_index("ts")
        part = pd.DataFrame(index=df.index)
        part["o"] = s * r * df["open"]
        part["c"] = s * r * df["close"]
        if s > 0:
            part["h"] = r * df["high"]
            part["l"] = r * df["low"]
        else:
            part["h"] = -r * df["low"]
            part["l"] = -r * df["high"]
        merged = part if merged is None else merged.add(part, fill_value=None)
    if merged is None:
        return pd.DataFrame()
    return merged.dropna().reset_index()


def historical_candles(legs, chart_type, timeframe):
    vl = valid_legs(legs)
    st.markdown(styles.section("📜 Historical Candles (today, market hours)"),
                unsafe_allow_html=True)
    if st.button("📈 Calculate & Plot", key="sp_hist_btn"):
        is_open, now = fc.market_status()
        if not vl:
            st.warning("Add at least one valid leg.")
            return
        today = now.date().isoformat()
        try:
            res = fc.resolution_for(timeframe)
            df = _spread_candles(vl, today, today, res)
        except Exception as e:
            st.error(f"Candle fetch failed: {e}")
            return
        if df.empty:
            msg = ("No candle data. Intraday candles are only available during/"
                   "after market hours on a trading day.")
            st.info(msg) if not is_open else st.warning(msg)
            return
        fig = go.Figure()
        if chart_type == "Candlestick":
            fig.add_trace(go.Candlestick(
                x=df["ts"], open=df["o"], high=df["h"], low=df["l"], close=df["c"],
                increasing_line_color=P["GREEN"], decreasing_line_color=P["RED"]))
        else:
            fig.add_trace(go.Scatter(x=df["ts"], y=df["c"], mode="lines",
                                     line=dict(color=P["BLUE"], width=2)))
        lay = styles.plotly_layout(height=420)
        lay["xaxis"]["rangeslider"] = dict(visible=False)
        fig.update_layout(**lay)
        st.plotly_chart(fig, use_container_width=True, key="sp_hist_chart")


# --- safety calculator -----------------------------------------------------
def _spread_bid_ask_ltp(legs, quotes):
    bid = ask = ltp = 0.0
    for lg in legs:
        q = quotes.get(fc.leg_to_symbol(lg), {})
        s, r = fc.leg_sign(lg), float(lg["ratio"])
        ltp += s * r * q.get("ltp", 0.0)
        if s > 0:
            bid += r * q.get("bid", 0.0)
            ask += r * q.get("ask", 0.0)
        else:
            bid += -r * q.get("ask", 0.0)
            ask += -r * q.get("bid", 0.0)
    return bid, ask, ltp


def safety_calculator(legs):
    vl = valid_legs(legs)
    st.markdown(styles.section("🛡️ Safety Calculator (live ladder)"),
                unsafe_allow_html=True)
    if not vl:
        st.info("Add valid legs above to build the ladder.")
        return

    cols = st.columns(len(vl) + 1)
    intervals = []
    for i, lg in enumerate(vl):
        default = fc.STRIKE_INTERVAL.get(lg["index"], 100)
        intervals.append(cols[i].number_input(
            f"L{i+1} interval", 1, 5000, default, step=1,
            key=f"sp_safe_int_{i}"))
    rows_n = cols[-1].number_input("Rows ±", 1, 10, 3, key="sp_safe_rows")

    # collect every symbol across every row in ONE batch quote
    all_syms = set()
    grid = {}  # offset -> list of shifted legs
    for off in range(-rows_n, rows_n + 1):
        shifted = []
        for i, lg in enumerate(vl):
            new = dict(lg)
            new["strike"] = int(lg["strike"]) + off * int(intervals[i])
            shifted.append(new)
            all_syms.add(fc.leg_to_symbol(new))
        grid[off] = shifted
    try:
        quotes = fc.get_quotes(list(all_syms))
    except Exception as e:
        st.error(f"Quote fetch failed: {e}")
        return

    # build HTML table (BASE=blue, interval header=orange)
    head = ("<th style='padding:6px 8px;text-align:left;'>SERIES</th>"
            + "".join(f"<th style='padding:6px 8px;'>L{i+1} STRIKE</th>"
                      for i in range(len(vl)))
            + "<th style='padding:6px 8px;'>BID</th>"
            + "<th style='padding:6px 8px;'>ASK</th>"
            + "<th style='padding:6px 8px;'>LTP</th>")
    body = []
    export_rows = []
    for off in range(rows_n, -rows_n - 1, -1):
        shifted = grid[off]
        bid, ask, ltp = _spread_bid_ask_ltp(shifted, quotes)
        if off == 0:
            label, bg = "BASE", P["BLUE"]
        elif off > 0:
            label, bg = f"+{off}", "transparent"
        else:
            label, bg = f"{off}", "transparent"
        tc = "#fff" if off == 0 else P["TEXT"]
        cells = (f"<td style='padding:6px 8px;color:{tc};font-weight:"
                 f"{'700' if off==0 else '400'};'>{label}</td>")
        for lg in shifted:
            cells += f"<td style='padding:6px 8px;text-align:center;color:{tc};'>{lg['strike']}</td>"
        cells += (f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{bid:,.2f}</td>"
                  f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{ask:,.2f}</td>"
                  f"<td style='padding:6px 8px;text-align:right;color:{tc};'>{ltp:,.2f}</td>")
        body.append(f"<tr style='background:{bg};border-bottom:1px solid "
                    f"{P['BORDER']};'>{cells}</tr>")
        row = {"SERIES": label}
        for i, lg in enumerate(shifted):
            row[f"L{i+1}_STRIKE"] = lg["strike"]
        row.update({"BID": round(bid, 2), "ASK": round(ask, 2), "LTP": round(ltp, 2)})
        export_rows.append(row)

    table = (f"<div style='overflow-x:auto;'><table style='width:100%;"
             f"border-collapse:collapse;background:{P['PANEL']};border:1px solid "
             f"{P['BORDER']};border-radius:6px;font-size:13px;color:{P['TEXT']};'>"
             f"<thead><tr style='color:{P['MUTED']};border-bottom:2px solid "
             f"{P['ORANGE']};'>{head}</tr></thead><tbody>"
             + "".join(body) + "</tbody></table></div>")
    st.markdown(table, unsafe_allow_html=True)

    df = pd.DataFrame(export_rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Safety")
    st.download_button("⬇️ Export to Excel", buf.getvalue(),
                       file_name="safety_ladder.xlsx", key="sp_safe_xl",
                       mime="application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet")


# --- entry point -----------------------------------------------------------
def render(user):
    top = st.columns([1, 1, 1])
    n_legs = top[0].number_input("Number of Legs", 2, 6, 2, key="sp_nlegs")
    chart_type = top[1].selectbox("Chart Type", ["Line", "Candlestick"],
                                  key="ui_chart_type")
    timeframe = top[2].selectbox("Timeframe", list(fc.TIMEFRAMES.keys()),
                                 key="ui_timeframe")

    st.markdown(styles.section("Legs"), unsafe_allow_html=True)
    legs = build_legs("sp", int(n_legs))
    st.session_state["legs_spread"] = legs

    if st.session_state.get("_fy_err"):
        st.caption(f"⚠️ Fyers: {st.session_state['_fy_err']}")

    quotes, spread_val = quote_table(valid_legs(legs)) if valid_legs(legs) else ({}, 0.0)

    mode = st.tabs(["📡 Live Feed", "📜 Historical Candles"])
    with mode[0]:
        live_feed(legs)
    with mode[1]:
        historical_candles(legs, chart_type, timeframe)

    st.markdown(styles.section("Summary"), unsafe_allow_html=True)
    if valid_legs(legs):
        summary_chips(valid_legs(legs), quotes, spread_val)

    if st.checkbox("Show Greeks", key="sp_greeks_tog") and valid_legs(legs):
        ng, avg_iv = net_greeks(valid_legs(legs), quotes)
        st.markdown(styles.chips_row([
            ("Net Delta", f"{ng['delta']:,.3f}", P["BLUE"]),
            ("Net Gamma", f"{ng['gamma']:,.5f}", P["GREEN"]),
            ("Net Vega", f"{ng['vega']:,.2f}", P["PURPLE"]),
            ("Net Theta", f"{ng['theta']:,.2f}", P["RED"]),
            ("Net IV %", f"{avg_iv:,.2f}", P["ORANGE"]),
        ]), unsafe_allow_html=True)

    safety_calculator(legs)
