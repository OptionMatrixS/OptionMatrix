import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
from fyers_client import (
    get_expiries, get_strikes, get_live_quote,
    get_spread_greeks, get_spot_price, validate_legs
)

_SS = st.session_state
INDICES = ["NIFTY","SENSEX","BANKNIFTY"]

def _init():
    if "st_n_spreads" not in _SS: _SS.st_n_spreads = 8
    if "st_show_greeks" not in _SS: _SS.st_show_greeks = False
    if "st_configs" not in _SS: _SS.st_configs = {}
    if "st_results" not in _SS: _SS.st_results = []

def _get_spread_data(cfg: dict, show_greeks: bool) -> dict:
    idx = cfg["index"]; exp1 = cfg["exp1"]; exp2 = cfg["exp2"]
    s1  = cfg["strike1"]; s2 = cfg["strike2"]; cp = cfg["cp"]
    try:
        q1 = get_live_quote(idx, s1, exp1, cp)
        q2 = get_live_quote(idx, s2, exp2, cp)
        bid  = round(q1["bid"]  - q2["ask"],  2)
        ask  = round(q1["ask"]  - q2["bid"],  2)
        ltp  = round(q1["ltp"]  - q2["ltp"],  2)
        prev = round(q1["prev_close"] - q2["prev_close"], 2)
        high = round(q1["high"] - q2["low"],  2)
        low  = round(q1["low"]  - q2["high"], 2)
        hl   = f"{high:.2f} - {low:.2f}"
        result = dict(bid=bid,ask=ask,ltp=ltp,prev=prev,hl=hl,
                      strike1=s1,strike2=s2,exp1=exp1,exp2=exp2,cp=cp,index=idx)
        if show_greeks:
            spot = get_spot_price(idx)
            legs = [
                dict(index=idx,strike=s1,expiry=exp1,cp=cp,bs="Buy",ratio=1,ltp=q1["ltp"],net=q1["ltp"]),
                dict(index=idx,strike=s2,expiry=exp2,cp=cp,bs="Sell",ratio=1,ltp=q2["ltp"],net=-q2["ltp"]),
            ]
            g = get_spread_greeks(legs, {idx: spot})
            result.update({"delta":g["delta"],"vega":g["vega"],"net_iv":g["net_iv"]})
        return result
    except Exception as e:
        return {"error":str(e),"strike1":s1,"strike2":s2,"exp1":exp1,"exp2":exp2,"cp":cp,"index":idx}

def _render_config(i: int) -> dict:
    key = f"st_{i}"; cfg = _SS.st_configs.get(key, {})
    idx = st.selectbox("Index",INDICES,key=f"{key}_idx")
    try:
        exps = get_expiries(idx)
    except Exception:
        exps = []
    if not exps: exps = ["—"]
    c1,c2 = st.columns(2)
    with c1: exp1 = st.selectbox("Expiry (Buy)",exps,key=f"{key}_exp1")
    with c2: exp2 = st.selectbox("Expiry (Sell)",exps,index=min(1,len(exps)-1),key=f"{key}_exp2")
    strikes1 = get_strikes(idx,exp1) if exp1!="—" else []
    if not strikes1: strikes1=[0]
    atm  = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx,22800)
    def_s= min(strikes1,key=lambda x:abs(x-atm))
    c3,c4 = st.columns(2)
    with c3: s1 = st.selectbox("Strike (Leg1)",strikes1,index=strikes1.index(def_s),key=f"{key}_s1")
    with c4:
        strikes2 = get_strikes(idx,exp2) if exp2!="—" else [0]
        if not strikes2: strikes2=[0]
        def_s2 = min(strikes2,key=lambda x:abs(x-atm))
        s2 = st.selectbox("Strike (Leg2)",strikes2,index=strikes2.index(def_s2),key=f"{key}_s2")
    c5,c6 = st.columns(2)
    with c5: cp = st.selectbox("CE/PE",["CE","PE"],key=f"{key}_cp")
    with c6: safety = st.selectbox("Safety",[ 2,3,4],key=f"{key}_safety")
    new_cfg = dict(index=idx,exp1=exp1,exp2=exp2,strike1=s1,strike2=s2,cp=cp,safety=safety)
    _SS.st_configs[key] = new_cfg
    return new_cfg

def _render_table(data: dict, i: int, show_greeks: bool):
    if "error" in data:
        st.markdown(f'<div style="background:#2b0d0d;border:1px solid #ef535040;border-radius:6px;'
                    f'padding:8px 12px;font-size:11px;color:#ef5350;">⚠ {data["error"]}</div>',
                    unsafe_allow_html=True); return
    ltp_c = "#26a69a" if data["ltp"]>=0 else "#ef5350"
    bid_c = "#26a69a" if data["bid"]>=0 else "#ef5350"
    ask_c = "#26a69a" if data["ask"]>=0 else "#ef5350"
    label = f"{data['index']} {data['strike1']}{data['cp']} {data['exp1']} / {data['strike2']}{data['cp']} {data['exp2']}"
    cols_def = ["SPREAD","BID","ASK","LTP","PREV CLOSE","HIGH-LOW"]
    if show_greeks: cols_def += ["NET DELTA","NET VEGA","NET IV"]
    col_html = "".join([f'<th style="padding:5px 8px;font-size:10px;color:#787b86;text-align:center;'
                        f'white-space:nowrap;border-bottom:1px solid #2a2e39;">{c}</th>' for c in cols_def])
    cells = [
        f'<td style="padding:6px 8px;font-size:11px;color:#d1d4dc;white-space:nowrap;">{label}</td>',
        f'<td style="padding:6px 8px;font-size:12px;color:{bid_c};text-align:center;">{data["bid"]:+.2f}</td>',
        f'<td style="padding:6px 8px;font-size:12px;color:{ask_c};text-align:center;">{data["ask"]:+.2f}</td>',
        f'<td style="padding:6px 8px;font-size:13px;font-weight:600;color:{ltp_c};text-align:center;">{data["ltp"]:+.2f}</td>',
        f'<td style="padding:6px 8px;font-size:12px;color:#d1d4dc;text-align:center;">{data["prev"]:+.2f}</td>',
        f'<td style="padding:6px 8px;font-size:12px;color:#d1d4dc;text-align:center;">{data["hl"]}</td>',
    ]
    if show_greeks:
        cells += [
            f'<td style="padding:6px 8px;font-size:12px;color:#2962ff;text-align:center;">{data.get("delta",0):+.4f}</td>',
            f'<td style="padding:6px 8px;font-size:12px;color:#9c27b0;text-align:center;">{data.get("vega",0):+.4f}</td>',
            f'<td style="padding:6px 8px;font-size:12px;color:#26a69a;text-align:center;">{data.get("net_iv",0):.2f}%</td>',
        ]
    row_html = f'<tr style="background:#1e222d;border-bottom:1px solid #2a2e39;">{"".join(cells)}</tr>'
    st.markdown(f'<div style="overflow-x:auto;border:1px solid #2a2e39;border-radius:6px;margin-bottom:4px;">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr style="background:#1a1f2e;">{col_html}</tr></thead>'
                f'<tbody>{row_html}</tbody></table></div>', unsafe_allow_html=True)

def render():
    _init()
    st.markdown('<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
                '<div style="font-size:20px;font-weight:600;color:#d1d4dc;">📋 Spread Tracker</div>'
                '<div style="font-size:11px;color:#787b86;padding:3px 10px;background:#1e222d;'
                'border:1px solid #2a2e39;border-radius:10px;">Calendar &amp; Diagonal</div></div>', unsafe_allow_html=True)

    tc1,tc2,tc3 = st.columns([1,1,2])
    with tc1: n_spreads = st.selectbox("No. of spreads",list(range(6,15)),index=_SS.st_n_spreads-6,key="st_n_sel"); _SS.st_n_spreads=n_spreads
    with tc2: show_greeks = st.checkbox("Show Greeks",value=_SS.st_show_greeks,key="st_greeks_chk"); _SS.st_show_greeks=show_greeks
    with tc3: fetch_btn = st.button("🔄  Fetch Live Data",use_container_width=True,type="primary")
    st.markdown("---")

    n_per_col = (n_spreads+1)//2
    all_configs = {}
    col_left, col_right = st.columns(2, gap="medium")
    COLORS = ["#2962ff","#26a69a","#ff9800","#ef5350","#9c27b0","#00bcd4","#8bc34a","#ff5722","#607d8b","#e91e63","#795548","#009688","#ffc107","#3f51b5"]
    for i in range(n_spreads):
        target_col = col_left if i < n_per_col else col_right
        with target_col:
            color = COLORS[i%len(COLORS)]
            st.markdown(f'<div style="font-size:11px;font-weight:600;color:{color};margin:8px 0 4px;'
                        f'padding:4px 10px;background:#1e222d;border-left:3px solid {color};border-radius:3px;">'
                        f'SPREAD {i+1}</div>', unsafe_allow_html=True)
            all_configs[i] = _render_config(i)
            st.markdown('<hr style="border-color:#2a2e39;margin:8px 0;">', unsafe_allow_html=True)

    if fetch_btn:
        with st.spinner("Fetching live data…"):
            results = []
            for i in range(n_spreads):
                cfg = all_configs.get(i, _SS.st_configs.get(f"st_{i}",{}))
                if cfg: results.append(_get_spread_data(cfg, show_greeks))
            _SS.st_results = results

    if _SS.st_results:
        st.markdown("---")
        st.markdown('<div class="sec-header">Live Spread Data</div>', unsafe_allow_html=True)
        for i,data in enumerate(_SS.st_results):
            color = COLORS[i%len(COLORS)]
            st.markdown(f'<div style="font-size:11px;font-weight:600;color:{color};margin:6px 0 2px;">SPREAD {i+1}</div>',
                        unsafe_allow_html=True)
            _render_table(data, i, show_greeks)
