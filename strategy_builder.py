"""
strategy_builder.py  —  Option Strategy Builder (Sensibull-style)
Payoff chart, Greeks, P&L simulation.
"""
import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import math
from fyers_client import (
    get_expiries, get_strikes, get_live_ltp, get_spot_price,
    bs_price, bs_greeks, implied_volatility,
    _label_to_code, RISK_FREE_RATE, _dte
)

_SS = st.session_state

INDICES  = ["NIFTY","SENSEX","BANKNIFTY","FINNIFTY"]
STRATEGY_PRESETS = {
    "Custom": [],
    "Bull Call Spread":   [("Buy","CE",0),("Sell","CE",1)],
    "Bear Put Spread":    [("Buy","PE",1),("Sell","PE",0)],
    "Long Straddle":      [("Buy","CE",0),("Buy","PE",0)],
    "Short Straddle":     [("Sell","CE",0),("Sell","PE",0)],
    "Long Strangle":      [("Buy","CE",1),("Buy","PE",-1)],
    "Short Strangle":     [("Sell","CE",1),("Sell","PE",-1)],
    "Iron Condor":        [("Buy","PE",-2),("Sell","PE",-1),("Sell","CE",1),("Buy","CE",2)],
    "Bull Put Spread":    [("Sell","PE",0),("Buy","PE",-1)],
    "Bear Call Spread":   [("Sell","CE",0),("Buy","CE",1)],
    "Long Call Butterfly":[("Buy","CE",-1),("Sell","CE",0),("Sell","CE",0),("Buy","CE",1)],
}


def _init():
    for k, v in [("sb_n_legs",2),("sb_index","NIFTY"),("sb_result",None),
                 ("sb_preset","Custom")]:
        if k not in _SS: _SS[k] = v


def _payoff_at_expiry(legs, spot_range):
    pnl = np.zeros(len(spot_range))
    for leg in legs:
        K     = leg["strike"]
        cp    = leg["cp"]
        qty   = leg["qty"]
        sign  = 1 if leg["bs"] == "Buy" else -1
        prem  = leg["premium"]
        if cp == "CE":
            intrinsic = np.maximum(spot_range - K, 0)
        else:
            intrinsic = np.maximum(K - spot_range, 0)
        pnl += sign * (intrinsic - prem) * qty
    return pnl


def _strategy_greeks(legs, spot):
    net = {"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"net_iv":0.}
    iv_list = []
    for leg in legs:
        try:
            K   = leg["strike"]; cp = leg["cp"]
            T   = leg.get("T", 30/365)
            prem= leg["premium"]
            sig = implied_volatility(prem, spot, K, T, RISK_FREE_RATE, cp)
            g   = bs_greeks(spot, K, T, RISK_FREE_RATE, sig, cp)
            sgn = 1 if leg["bs"]=="Buy" else -1
            qty = leg["qty"]
            for k in ("delta","gamma","vega","theta"):
                net[k] += sgn * qty * g[k]
            iv_list.append(g["iv"])
        except Exception:
            pass
    net["net_iv"] = round(sum(iv_list)/len(iv_list), 2) if iv_list else 0.
    return {k: round(v, 4) for k,v in net.items()}


def render():
    _init()
    st.markdown(
        '<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">'
        '🏗️ Strategy Builder</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:12px;color:#787b86;margin-bottom:12px;">'
        'Build multi-leg strategies · Payoff chart · Greeks · P&L simulation</div>',
        unsafe_allow_html=True)

    # ── Controls ───────────────────────────────────────────────────────────────
    ctrl = st.columns([1,1,1,1,2])
    with ctrl[0]:
        index = st.selectbox("Index / Underlying", INDICES, key="sb_index_sel")
    with ctrl[1]:
        try:
            exps   = get_expiries(index)
            expiry = st.selectbox("Expiry", exps, key="sb_expiry")
        except Exception as e:
            st.error(f"Load expiries: {e}"); return
    with ctrl[2]:
        n_legs = st.selectbox("Number of Legs", list(range(2,11)),
                               index=_SS.sb_n_legs-2, key="sb_n_legs_sel")
        _SS.sb_n_legs = n_legs
    with ctrl[3]:
        preset = st.selectbox("Strategy Preset", list(STRATEGY_PRESETS.keys()),
                               key="sb_preset")
    with ctrl[4]:
        try:
            spot = get_spot_price(index)
        except Exception:
            spot = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(index,22800)
        st.markdown(
            f'<div style="padding-top:28px;font-size:13px;color:#d1d4dc;">'
            f'Spot: <b style="color:#26a69a;">{spot:,.0f}</b></div>',
            unsafe_allow_html=True)

    # ── Strikes ────────────────────────────────────────────────────────────────
    try:
        strikes = get_strikes(index, expiry)
    except Exception:
        atm  = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(index,22800)
        step = 50 if index=="NIFTY" else (100 if index=="BANKNIFTY" else 500)
        strikes = list(range(atm-20*step, atm+21*step, step))

    atm_strike = min(strikes, key=lambda x: abs(x-spot)) if strikes else 22800
    step       = (strikes[1]-strikes[0]) if len(strikes)>1 else 50
    preset_legs= STRATEGY_PRESETS.get(preset, [])

    # ── Leg builder ────────────────────────────────────────────────────────────
    st.markdown("---")
    cols_hdr = st.columns([0.5,1,1,1,1,1,1,1])
    for col,hdr in zip(cols_hdr,["Leg","B/S","CE/PE","Strike","Qty","Premium","IV%","Δ Delta"]):
        col.markdown(f'<div style="font-size:10px;color:#787b86;font-weight:600;">{hdr}</div>',
                     unsafe_allow_html=True)

    legs = []
    T    = _dte(expiry, index)

    for i in range(n_legs):
        p_bs  = preset_legs[i][0] if i < len(preset_legs) else ("Buy" if i%2==0 else "Sell")
        p_cp  = preset_legs[i][1] if i < len(preset_legs) else "CE"
        p_off = preset_legs[i][2] if i < len(preset_legs) else 0
        def_strike = min(strikes, key=lambda x: abs(x-(atm_strike + p_off*step))) if strikes else atm_strike

        leg_cols = st.columns([0.5,1,1,1,1,1,1,1])
        colors = ["#2962ff","#26a69a","#ff9800","#ef5350","#9c27b0",
                  "#00bcd4","#8bc34a","#ff5722","#607d8b","#e91e63"]
        with leg_cols[0]:
            st.markdown(f'<div style="padding-top:8px;font-size:11px;font-weight:600;'
                        f'color:{colors[i%10]};">L{i+1}</div>', unsafe_allow_html=True)
        with leg_cols[1]:
            bs = st.selectbox("", ["Buy","Sell"], key=f"sb_bs_{i}",
                              index=0 if p_bs=="Buy" else 1,
                              label_visibility="collapsed")
        with leg_cols[2]:
            cp = st.selectbox("", ["CE","PE"], key=f"sb_cp_{i}",
                              index=0 if p_cp=="CE" else 1,
                              label_visibility="collapsed")
        with leg_cols[3]:
            cur  = _SS.get(f"sb_strike_{i}", def_strike)
            didx = strikes.index(cur) if cur in strikes else \
                   (strikes.index(def_strike) if def_strike in strikes else 0)
            strike = st.selectbox("", strikes, index=didx,
                                  key=f"sb_strike_{i}", label_visibility="collapsed")
        with leg_cols[4]:
            qty = st.number_input("", min_value=1, max_value=100, value=1,
                                  key=f"sb_qty_{i}", label_visibility="collapsed")
        with leg_cols[5]:
            try:
                live_prem = get_live_ltp(index, strike, expiry, cp)
            except Exception:
                live_prem = 0.0
            prem = st.number_input("", min_value=0.0,
                                   value=float(round(live_prem, 2)),
                                   step=0.5, key=f"sb_prem_{i}",
                                   label_visibility="collapsed")
        with leg_cols[6]:
            try:
                iv = implied_volatility(prem, spot, strike, T, RISK_FREE_RATE, cp) * 100
                st.markdown(f'<div style="padding-top:8px;font-size:12px;color:#ff9800;">'
                            f'{iv:.1f}%</div>', unsafe_allow_html=True)
            except Exception:
                iv = 0.
                st.markdown('<div style="padding-top:8px;color:#787b86;">—</div>',
                            unsafe_allow_html=True)
        with leg_cols[7]:
            try:
                sig = iv/100 if iv > 0 else 0.2
                g   = bs_greeks(spot, strike, T, RISK_FREE_RATE, sig, cp)
                sgn = 1 if bs=="Buy" else -1
                st.markdown(
                    f'<div style="padding-top:6px;font-size:10px;color:#787b86;">'
                    f'Δ {sgn*g["delta"]:+.3f}</div>', unsafe_allow_html=True)
            except Exception:
                st.markdown('<div style="padding-top:8px;color:#787b86;">—</div>',
                            unsafe_allow_html=True)

        legs.append(dict(bs=bs, cp=cp, strike=strike, qty=qty,
                         premium=prem, T=T, index=index, expiry=expiry))

    # ── Calculate ──────────────────────────────────────────────────────────────
    st.markdown("")
    if st.button("📊  Build Payoff Chart", type="primary", key="sb_calc"):
        _SS.sb_result = {"legs":legs,"spot":spot,"index":index,
                          "expiry":expiry,"step":step}
        st.rerun()

    # ── Output ─────────────────────────────────────────────────────────────────
    if _SS.get("sb_result"):
        r     = _SS.sb_result
        legs  = r["legs"]
        spot  = r["spot"]
        step  = r["step"]

        lo         = spot * 0.80
        hi         = spot * 1.20
        spot_range = np.linspace(lo, hi, 300)
        pnl        = _payoff_at_expiry(legs, spot_range)

        net_prem   = sum((-1 if l["bs"]=="Buy" else 1)*l["premium"]*l["qty"] for l in legs)
        max_profit = float(pnl.max())
        max_loss   = float(pnl.min())
        sign_chg   = np.where(np.diff(np.sign(pnl)))[0]
        breakevens = [round(float(spot_range[i]),0) for i in sign_chg]

        # Payoff chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=spot_range, y=np.where(pnl>=0, pnl, 0),
            fill="tozeroy", fillcolor="rgba(38,166,154,0.15)",
            line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=spot_range, y=np.where(pnl<=0, pnl, 0),
            fill="tozeroy", fillcolor="rgba(239,83,80,0.15)",
            line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=spot_range, y=pnl, mode="lines", name="P&L at Expiry",
            line=dict(color="#2962ff", width=2.5),
            hovertemplate="Spot: %{x:,.0f}<br>P&L: ₹%{y:,.2f}<extra></extra>"))
        fig.add_vline(x=spot, line=dict(color="#787b86",width=1,dash="dash"),
                      annotation_text=f"Spot {spot:,.0f}",
                      annotation_font=dict(color="#787b86",size=10))
        for be in breakevens:
            fig.add_vline(x=be, line=dict(color="#ff9800",width=1,dash="dot"),
                          annotation_text=f"BE {be:,.0f}",
                          annotation_font=dict(color="#ff9800",size=9))
        fig.add_hline(y=0, line=dict(color="#363a45",width=1))
        fig.update_layout(
            title=dict(text=f"Strategy Payoff — {r['index']} {r['expiry']}",
                       font=dict(size=13,color="#d1d4dc"),x=0),
            paper_bgcolor="#131722", plot_bgcolor="#131722",
            xaxis=dict(gridcolor="#1e222d",tickfont=dict(size=10,color="#787b86"),
                       showline=False,zeroline=False,
                       title=dict(text="Underlying Price",font=dict(color="#787b86"))),
            yaxis=dict(gridcolor="#1e222d",tickfont=dict(size=10,color="#787b86"),
                       showline=False,zeroline=False,side="right",
                       title=dict(text="P&L (₹)",font=dict(color="#787b86"))),
            margin=dict(l=10,r=80,t=50,b=40), height=420,
            hovermode="x unified", dragmode="pan",
            hoverlabel=dict(bgcolor="#1e222d",bordercolor="#2a2e39",
                            font=dict(size=11,color="#d1d4dc")))
        st.plotly_chart(fig, use_container_width=True,
                        config={"scrollZoom":True,"displaylogo":False})

        # Summary chips
        chip_data = [
            ("Net Premium",  f"₹{net_prem:+,.2f}",  "#d1d4dc"),
            ("Max Profit",   "Unlimited" if max_profit>1e6 else f"₹{max_profit:,.0f}", "#26a69a"),
            ("Max Loss",     f"₹{max_loss:,.0f}",   "#ef5350"),
            ("Breakevens",   " / ".join([f"{b:,.0f}" for b in breakevens]) or "—", "#ff9800"),
        ]
        for col,(lbl,val,clr) in zip(st.columns(4), chip_data):
            col.markdown(
                f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:8px;'
                f'padding:10px 16px;text-align:center;">'
                f'<div style="font-size:11px;color:#787b86;">{lbl}</div>'
                f'<div style="font-size:15px;font-weight:600;color:{clr};">{val}</div></div>',
                unsafe_allow_html=True)

        # Net Greeks
        st.markdown("**Net Greeks**")
        net_g = _strategy_greeks(legs, spot)
        for col,(lbl,key,clr) in zip(st.columns(5),[
            ("Net Δ Delta","delta","#2962ff"),("Net Γ Gamma","gamma","#ff9800"),
            ("Net V Vega","vega","#9c27b0"),("Net Θ Theta","theta","#ef5350"),
            ("Net IV","net_iv","#26a69a")
        ]):
            val = f"{net_g[key]:+.4f}" if key!="net_iv" else f"{net_g[key]:.2f}%"
            col.markdown(
                f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:8px;'
                f'padding:8px 12px;text-align:center;margin-top:8px;">'
                f'<div style="font-size:10px;color:#787b86;">{lbl}</div>'
                f'<div style="font-size:13px;font-weight:600;color:{clr};">{val}</div></div>',
                unsafe_allow_html=True)

        # P&L simulation table
        st.markdown("**P&L Simulation**")
        sim_spots = [spot*(1+x/100) for x in [-10,-8,-5,-3,-2,-1,0,1,2,3,5,8,10]]
        sim_pnl   = _payoff_at_expiry(legs, np.array(sim_spots))
        sim_df    = pd.DataFrame({
            "Spot Price": [f"{s:,.0f}" for s in sim_spots],
            "Change %":   [f"{(s/spot-1)*100:+.1f}%" for s in sim_spots],
            "P&L (₹)":    [f"₹{p:,.2f}" for p in sim_pnl],
        })
        st.dataframe(sim_df, use_container_width=True, hide_index=True)

        # Leg summary
        st.markdown("**Leg Summary**")
        leg_rows = []
        for i,l in enumerate(legs):
            sign = 1 if l["bs"]=="Buy" else -1
            try:
                sig = implied_volatility(l["premium"],spot,l["strike"],l["T"],RISK_FREE_RATE,l["cp"])
                g   = bs_greeks(spot,l["strike"],l["T"],RISK_FREE_RATE,sig,l["cp"])
                iv_ = round(sig*100,1); d_=round(sign*l["qty"]*g["delta"],3)
                t_  = round(sign*l["qty"]*g["theta"],2)
            except Exception:
                iv_=d_=t_="—"
            leg_rows.append({"Leg":f"L{i+1}","B/S":l["bs"],"Type":l["cp"],
                             "Strike":l["strike"],"Qty":l["qty"],"Premium":l["premium"],
                             "IV%":iv_,"Net Δ":d_,"Net θ":t_})
        st.dataframe(pd.DataFrame(leg_rows), use_container_width=True, hide_index=True)
