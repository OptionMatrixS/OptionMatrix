"""
spread_tracker.py — Spread Tracker with Safety Rows
Each spread shows the base strikes PLUS ±N rows offset by a user-defined interval.
Output: SERIES (-N…0…+N), LEG1 strike, LEG2 strike, BID, ASK, LTP for each row.
"""
import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import io
from fyers_client import (
    get_expiries, get_strikes, get_live_quote,
    get_spread_greeks, get_spot_price, validate_legs
)

_SS = st.session_state
INDICES = ["NIFTY","SENSEX","BANKNIFTY"]
COLORS  = ["#2962ff","#26a69a","#ff9800","#ef5350","#9c27b0",
           "#00bcd4","#8bc34a","#ff5722","#607d8b","#e91e63",
           "#795548","#009688","#ffc107","#3f51b5"]

def _init():
    for k,v in [("st_n_spreads",4),("st_show_greeks",False),
                ("st_configs",{}),("st_results",[])]:
        if k not in _SS: _SS[k] = v

def _live_quote_safe(idx, strike, expiry, cp):
    try:
        return get_live_quote(idx, strike, expiry, cp)
    except Exception:
        return {"ltp":0,"bid":0,"ask":0,"prev_close":0,"high":0,"low":0}

def _nearest(strikes, target):
    if not strikes: return target
    return min(strikes, key=lambda x: abs(x - target))

def _get_spread_rows(cfg, show_greeks):
    """
    Returns list of row-dicts for this spread, one per safety offset.
    Row 0 = base strikes. Row ±k = base ± k*interval.
    """
    idx      = cfg["index"]
    exp1     = cfg["exp1"]
    exp2     = cfg["exp2"]
    s1_base  = cfg["strike1"]
    s2_base  = cfg["strike2"]
    cp       = cfg["cp"]
    interval = cfg["interval"]   # step per row e.g. 100
    n_safety = cfg["n_safety"]   # rows above and below 0

    try:
        strikes1 = get_strikes(idx, exp1)
        strikes2 = get_strikes(idx, exp2)
    except Exception:
        strikes1 = strikes2 = []

    rows = []
    for offset in range(-n_safety, n_safety + 1):
        s1 = _nearest(strikes1, s1_base + offset * interval)
        s2 = _nearest(strikes2, s2_base + offset * interval)

        q1 = _live_quote_safe(idx, s1, exp1, cp)
        q2 = _live_quote_safe(idx, s2, exp2, cp)

        bid = round(q1["bid"] - q2["ask"], 2)
        ask = round(q1["ask"] - q2["bid"], 2)
        ltp = round(q1["ltp"] - q2["ltp"], 2)
        prev= round(q1["prev_close"] - q2["prev_close"], 2)
        hi  = round(q1["high"] - q2["low"], 2)
        lo  = round(q1["low"]  - q2["high"], 2)

        row = {
            "series":   offset,
            "strike1":  s1,
            "strike2":  s2,
            "bid":      bid,
            "ask":      ask,
            "ltp":      ltp,
            "prev":     prev,
            "hl":       f"{hi:.2f} / {lo:.2f}",
            "is_base":  (offset == 0),
        }

        if show_greeks:
            try:
                legs = [
                    dict(index=idx,strike=s1,expiry=exp1,cp=cp,
                         bs="Buy",ratio=1,ltp=q1["ltp"],net=q1["ltp"]),
                    dict(index=idx,strike=s2,expiry=exp2,cp=cp,
                         bs="Sell",ratio=1,ltp=q2["ltp"],net=-q2["ltp"]),
                ]
                spot = get_spot_price(idx)
                g    = get_spread_greeks(legs, {idx: spot})
                row.update({"delta":g["delta"],"vega":g["vega"],"net_iv":g["net_iv"]})
            except Exception:
                row.update({"delta":0,"vega":0,"net_iv":0})

        rows.append(row)
    return rows

def _render_spread_table(spread_num, rows, show_greeks, color):
    if not rows:
        st.warning("No data."); return

    cfg_key = f"st_{spread_num}"
    cfg     = _SS.st_configs.get(cfg_key, {})
    idx     = cfg.get("index","")
    exp1    = cfg.get("exp1",""); exp2 = cfg.get("exp2","")
    cp      = cfg.get("cp","")
    ivl     = cfg.get("interval",100)
    n_s     = cfg.get("n_safety",2)

    st.markdown(
        f'<div style="font-size:11px;font-weight:600;color:{color};margin:8px 0 4px;'
        f'padding:4px 10px;background:#1e222d;border-left:3px solid {color};border-radius:3px;">'
        f'SPREAD {spread_num+1} — {idx} {cp} | Buy:{exp1} / Sell:{exp2} | '
        f'Interval:{ivl} | Safety:{n_s}</div>', unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    cols_def = ["SERIES","STRIKE INTERVAL","LEG 1","LEG 2","BID","ASK","LTP","PREV CLOSE","HIGH/LOW"]
    if show_greeks: cols_def += ["DELTA","VEGA","NET IV"]

    header_html = "".join(
        f'<th style="padding:5px 10px;font-size:10px;color:#787b86;'
        f'text-align:center;white-space:nowrap;border-bottom:1px solid #2a2e39;">{c}</th>'
        for c in cols_def)

    # ── Rows ──────────────────────────────────────────────────────────────────
    rows_html = ""
    for row in rows:
        is_base = row["is_base"]
        bg      = "#162040" if is_base else "#1e222d"
        bl      = f"border-left:3px solid {color};" if is_base else "border-left:3px solid transparent;"
        series  = int(row["series"])

        def cell(val, c="#d1d4dc", fw="400", mono=False):
            ff = "font-family:'JetBrains Mono',monospace;" if mono else ""
            return (f'<td style="padding:6px 10px;font-size:11px;{ff}'
                    f'color:{c};font-weight:{fw};text-align:center;">{val}</td>')

        ltp_c = "#26a69a" if row["ltp"]>=0 else "#ef5350"
        bid_c = "#26a69a" if row["bid"]>=0 else "#ef5350"
        ask_c = "#26a69a" if row["ask"]>=0 else "#ef5350"

        row_cells = (
            cell(f"{series:+d}" if series != 0 else "0 (BASE)",
                 c=color if is_base else "#787b86", fw="700" if is_base else "400")
            + cell(f"{series * cfg.get('interval',100):+d}" if series != 0 else "—",
                   c="#ff9800" if is_base else "#787b86")
            + cell(row["strike1"], c="#ffffff" if is_base else "#d1d4dc",
                   fw="600" if is_base else "400", mono=True)
            + cell(row["strike2"], c="#ffffff" if is_base else "#d1d4dc",
                   fw="600" if is_base else "400", mono=True)
            + cell(f'{row["bid"]:+.2f}', c=bid_c, mono=True)
            + cell(f'{row["ask"]:+.2f}', c=ask_c, mono=True)
            + cell(f'{row["ltp"]:+.2f}', c=ltp_c, fw="600" if is_base else "400", mono=True)
            + cell(f'{row["prev"]:+.2f}', mono=True)
            + cell(row["hl"])
        )
        if show_greeks:
            row_cells += (
                cell(f'{row.get("delta",0):+.4f}', c="#2962ff", mono=True)
                + cell(f'{row.get("vega",0):+.4f}', c="#9c27b0", mono=True)
                + cell(f'{row.get("net_iv",0):.2f}%', c="#26a69a", mono=True)
            )

        rows_html += f'<tr style="background:{bg};{bl}border-bottom:1px solid #2a2e39;">{row_cells}</tr>'

    st.markdown(
        f'<div style="overflow-x:auto;border:1px solid #2a2e39;border-radius:6px;margin-bottom:8px;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="background:#1a1f2e;">{header_html}</tr></thead>'
        f'<tbody>{rows_html}</tbody></table></div>',
        unsafe_allow_html=True)

def render():
    _init()
    st.markdown(
        '<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">'
        '📋 Spread Tracker</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:12px;color:#787b86;margin-bottom:12px;">'
        'Calendar/Diagonal spreads with safety rows. '
        'Row 0 = your base strikes. ±N = offset by Strike Interval.</div>',
        unsafe_allow_html=True)

    # ── Global controls ────────────────────────────────────────────────────────
    tc1,tc2,tc3,tc4 = st.columns([1,1,1,2])
    with tc1:
        n_spreads = st.selectbox("No. of spreads", list(range(1,11)),
                                  index=_SS.st_n_spreads-1, key="st_n_sel")
        _SS.st_n_spreads = n_spreads
    with tc2:
        show_greeks = st.checkbox("Show Greeks", value=_SS.st_show_greeks, key="st_greeks_chk")
        _SS.st_show_greeks = show_greeks
    with tc3:
        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    with tc4:
        fetch_btn = st.button("🔄  Fetch All Live Data", use_container_width=True, type="primary")

    st.markdown("---")

    # ── Per-spread config ──────────────────────────────────────────────────────
    all_configs = {}
    col_left, col_right = st.columns(2, gap="medium")
    n_per_col = (n_spreads + 1) // 2

    for i in range(n_spreads):
        target_col = col_left if i < n_per_col else col_right
        key        = f"st_{i}"
        color      = COLORS[i % len(COLORS)]

        with target_col:
            st.markdown(
                f'<div style="font-size:11px;font-weight:600;color:{color};margin:8px 0 4px;'
                f'padding:4px 10px;background:#1e222d;border-left:3px solid {color};border-radius:3px;">'
                f'SPREAD {i+1}</div>', unsafe_allow_html=True)

            # Row 1: Index | CE/PE | Buy Expiry | Sell Expiry
            r1c1, r1c2, r1c3, r1c4 = st.columns(4)
            with r1c1: idx = st.selectbox("Index", INDICES, key=f"{key}_idx")
            with r1c2: cp  = st.selectbox("CE/PE", ["CE","PE"], key=f"{key}_cp")

            try:   exps = get_expiries(idx)
            except: exps = ["—"]
            if not exps: exps = ["—"]

            with r1c3: exp1 = st.selectbox("Buy Expiry",  exps,                            key=f"{key}_exp1")
            with r1c4: exp2 = st.selectbox("Sell Expiry", exps, index=min(1,len(exps)-1), key=f"{key}_exp2")

            # Row 2: Strike 1 | Strike 2 | Strike Interval | Safety rows
            try:   strikes1 = get_strikes(idx, exp1)
            except: strikes1 = [0]
            try:   strikes2 = get_strikes(idx, exp2)
            except: strikes2 = [0]
            if not strikes1: strikes1 = [0]
            if not strikes2: strikes2 = [0]

            atm   = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx,22800)
            def_s = min(strikes1, key=lambda x: abs(x - atm))

            r2c1, r2c2, r2c3, r2c4 = st.columns(4)
            with r2c1:
                cur_s1 = _SS.get(f"{key}_s1_val", def_s)
                didx1  = strikes1.index(cur_s1) if cur_s1 in strikes1 else strikes1.index(def_s)
                s1     = st.selectbox("Strike 1", strikes1, index=didx1, key=f"{key}_s1")
                _SS[f"{key}_s1_val"] = s1
            with r2c2:
                def_s2 = min(strikes2, key=lambda x: abs(x - atm))
                cur_s2 = _SS.get(f"{key}_s2_val", def_s2)
                didx2  = strikes2.index(cur_s2) if cur_s2 in strikes2 else strikes2.index(def_s2)
                s2     = st.selectbox("Strike 2", strikes2, index=didx2, key=f"{key}_s2")
                _SS[f"{key}_s2_val"] = s2
            with r2c3:
                default_ivl = 100 if idx in ("NIFTY","BANKNIFTY") else 500
                interval    = st.number_input("Strike Interval", min_value=1, max_value=5000,
                                               value=int(_SS.get(f"{key}_ivl", default_ivl)),
                                               step=default_ivl, key=f"{key}_interval")
                _SS[f"{key}_ivl"] = interval
            with r2c4:
                n_safety = st.selectbox("Safety Rows", [1,2,3,4,5],
                                         index=1, key=f"{key}_safety")

            cfg = dict(index=idx, exp1=exp1, exp2=exp2,
                       strike1=s1, strike2=s2, cp=cp,
                       interval=interval, n_safety=n_safety)
            _SS.st_configs[key] = cfg
            all_configs[i]      = cfg

            st.markdown('<hr style="border-color:#2a2e39;margin:8px 0;">', unsafe_allow_html=True)

    # ── Fetch + display results ────────────────────────────────────────────────
    if fetch_btn:
        with st.spinner("Fetching live data for all spreads…"):
            results = []
            for i in range(n_spreads):
                cfg = all_configs.get(i, _SS.st_configs.get(f"st_{i}", {}))
                if cfg:
                    try:
                        rows = _get_spread_rows(cfg, show_greeks)
                    except Exception as e:
                        rows = [{"error": str(e)}]
                    results.append(rows)
            _SS.st_results = results

    if _SS.st_results:
        st.markdown("---")
        st.markdown('<div class="sec-header">Live Spread Data with Safety Rows</div>',
                    unsafe_allow_html=True)
        for i, rows in enumerate(_SS.st_results):
            if not rows: continue
            color = COLORS[i % len(COLORS)]
            # Check for error
            if len(rows) == 1 and "error" in rows[0]:
                st.error(f"Spread {i+1}: {rows[0]['error']}")
                continue
            _render_spread_table(i, rows, show_greeks, color)
