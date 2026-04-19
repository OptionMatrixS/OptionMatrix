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
    """Calculate strategy P&L at expiry for each spot price."""
    pnl = np.zeros(len(spot_range))
    for leg in legs:
        K     = leg["strike"]
        cp    = leg["cp"]
        qty   = leg["qty"]
        sign  = 1 if leg["bs"] == "Buy" else -1
        prem  = leg["premium"]
        # Intrinsic value at expiry
        if cp == "CE":
            intrinsic = np.maximum(spot_range - K, 0)
        else:
            intrinsic = np.maximum(K - spot_range, 0)
        # P&L per unit = (intrinsic - premium_paid) * sign
        pnl += sign * (intrinsic - prem) * qty
    return pnl

def _strategy_greeks(legs, spot):
    """Net Greeks for all legs."""
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
    LOT_SIZE = {"NIFTY": 75, "SENSEX": 20, "BANKNIFTY": 35, "FINNIFTY": 40}

    ctrl = st.columns([1, 1, 2])
    with ctrl[0]:
        n_legs = st.selectbox("Number of Legs", list(range(2, 11)),
                               index=_SS.sb_n_legs - 2, key="sb_n_legs_sel")
        _SS.sb_n_legs = n_legs
    with ctrl[1]:
        preset = st.selectbox("Strategy Preset", list(STRATEGY_PRESETS.keys()),
                               key="sb_preset")
    with ctrl[2]:
        st.markdown(
            '<div style="font-size:11px;color:#787b86;padding-top:28px;">' +
            " &nbsp; ".join([f"<b style='color:#d1d4dc;'>{k}</b>: {v} lots"
                             for k,v in LOT_SIZE.items()]) +
            '</div>', unsafe_allow_html=True)

    # ── Leg builder — per-leg index/expiry/strike ─────────────────────────────
    preset_legs = STRATEGY_PRESETS.get(preset, [])
    st.markdown('<div class="sec-header" style="margin-top:8px;">Leg Configuration</div>',
                unsafe_allow_html=True)

    legs = []
    for i in range(n_legs):
        p_bs = preset_legs[i][0] if i < len(preset_legs) else ("Buy" if i%2==0 else "Sell")
        p_cp = preset_legs[i][1] if i < len(preset_legs) else "CE"
        color = ["#2962ff","#26a69a","#ff9800","#ef5350","#9c27b0",
                 "#00bcd4","#8bc34a","#ff5722","#607d8b","#e91e63"][i%10]

        st.markdown(
            f'<div style="font-size:10px;color:{color};font-weight:600;background:#1e222d;' +
            f'padding:3px 10px;border-left:3px solid {color};border-radius:3px;margin-top:6px;">LEG {i+1}</div>',
            unsafe_allow_html=True)

        lc = st.columns([1,1,1,1,1,1,1])
        # Per-leg index
        with lc[0]:
            leg_idx = st.selectbox("Index", INDICES, key=f"sb_idx_{i}",
                                   label_visibility="visible")
        # Per-leg expiry
        with lc[1]:
            try:
                leg_exps = get_expiries(leg_idx)
                leg_expiry = st.selectbox("Expiry", leg_exps, key=f"sb_exp_{i}",
                                           label_visibility="visible")
            except Exception:
                st.markdown('<div style="font-size:11px;color:#ff9800;">⏳ expiries…</div>',
                            unsafe_allow_html=True)
                legs.append(dict(bs=p_bs, cp=p_cp, strike=0, lots=1,
                                 premium=0, T=30/365, index=leg_idx, expiry=""))
                continue
        # Per-leg strikes
        try:
            leg_strikes = get_strikes(leg_idx, leg_expiry)
        except Exception:
            atm_  = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(leg_idx,22800)
            step_ = 50 if leg_idx=="NIFTY" else (100 if leg_idx=="BANKNIFTY" else 500)
            leg_strikes = list(range(atm_-20*step_, atm_+21*step_, step_))
        atm_leg = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(leg_idx,22800)
        try:
            spot_leg = get_spot_price(leg_idx)
            atm_leg  = min(leg_strikes, key=lambda x: abs(x-spot_leg)) if leg_strikes else atm_leg
        except Exception:
            pass
        def_stk = min(leg_strikes, key=lambda x: abs(x-atm_leg)) if leg_strikes else atm_leg
        try:
            spot_leg
        except NameError:
            spot_leg = atm_leg

        with lc[2]:
            bs = st.selectbox("B/S", ["Buy","Sell"], key=f"sb_bs_{i}",
                              index=0 if p_bs=="Buy" else 1)
        with lc[3]:
            cp = st.selectbox("CE/PE", ["CE","PE"], key=f"sb_cp_{i}",
                              index=0 if p_cp=="CE" else 1)
        with lc[4]:
            cur_stk = _SS.get(f"sb_strike_{i}", def_stk)
            s_idx   = leg_strikes.index(cur_stk) if cur_stk in leg_strikes else leg_strikes.index(def_stk) if def_stk in leg_strikes else 0
            strike  = st.selectbox("Strike", leg_strikes, index=s_idx, key=f"sb_strike_{i}")
        with lc[5]:
            default_lots = 1
            lots = st.number_input(f"Lots (1 lot = {LOT_SIZE.get(leg_idx,1)})",
                                   min_value=1, max_value=100, value=default_lots,
                                   key=f"sb_lots_{i}")
        with lc[6]:
            try:
                live_prem = get_live_ltp(leg_idx, strike, leg_expiry, cp)
            except Exception:
                live_prem = 0.0
            prem = st.number_input("Premium", min_value=0.0,
                                   value=float(round(live_prem, 2)),
                                   step=0.5, key=f"sb_prem_{i}",
                                   help="Auto-fetched. Edit to override.")

        T = _dte(leg_expiry, leg_idx)
        qty_actual = lots * LOT_SIZE.get(leg_idx, 1)

        # Show IV + delta inline
        try:
            iv  = implied_volatility(prem, spot_leg, strike, T, RISK_FREE_RATE, cp) * 100
            g   = bs_greeks(spot_leg, strike, T, RISK_FREE_RATE, iv/100 if iv>0 else 0.2, cp)
            sgn = 1 if bs == "Buy" else -1
            st.markdown(
                f'<div style="font-size:10px;color:#787b86;margin-top:2px;">' +
                f'IV: <span style="color:#ff9800;">{iv:.1f}%</span> &nbsp; ' +
                f'Δ: <span style="color:#2962ff;">{sgn*g["delta"]:+.3f}</span> &nbsp; ' +
                f'Qty: <span style="color:#d1d4dc;">{qty_actual}</span></div>',
                unsafe_allow_html=True)
        except Exception:
            iv = 0.

        legs.append(dict(bs=bs, cp=cp, strike=strike, qty=qty_actual, lots=lots,
                         premium=prem, T=T, index=leg_idx, expiry=leg_expiry))

    # ── Calculate ──────────────────────────────────────────────────────────────
    if st.button("📊  Build Payoff Chart", type="primary",
                  use_container_width=False, key="sb_calc"):
        _SS.sb_result = {"legs": legs, "spot": spot, "index": index,
                          "expiry": expiry, "step": step}
        st.rerun()

    # ── Output ─────────────────────────────────────────────────────────────────
    if _SS.sb_result:
        r     = _SS.sb_result
        legs  = r["legs"]
        spot  = r["spot"]
        step  = r["step"]

        # Spot range for payoff ±20% from ATM
        lo        = spot * 0.80
        hi        = spot * 1.20
        spot_range= np.linspace(lo, hi, 300)
        # Use first leg's index for spot range center
        first_spot = legs[0].get('strike', 22800) if legs else 22800
        lo = first_spot * 0.80; hi = first_spot * 1.20
        spot_range = np.linspace(lo, hi, 300)
        pnl       = _payoff_at_expiry(legs, spot_range)

        # Net premium
        net_prem = sum(
            (-1 if l["bs"]=="Buy" else 1) * l["premium"] * l["qty"]
            for l in legs)
        max_profit = float(pnl.max())
        max_loss   = float(pnl.min())
        # Breakevens
        sign_changes = np.where(np.diff(np.sign(pnl)))[0]
        breakevens   = [round(spot_range[i],0) for i in sign_changes]

        # ── Payoff chart ───────────────────────────────────────────────────────
        fig = go.Figure()
        # Fill positive
        fig.add_trace(go.Scatter(
            x=spot_range, y=np.where(pnl>=0, pnl, 0),
            fill="tozeroy", fillcolor="rgba(38,166,154,0.15)",
            line=dict(width=0), showlegend=False, hoverinfo="skip"))
        # Fill negative
        fig.add_trace(go.Scatter(
            x=spot_range, y=np.where(pnl<=0, pnl, 0),
            fill="tozeroy", fillcolor="rgba(239,83,80,0.15)",
            line=dict(width=0), showlegend=False, hoverinfo="skip"))
        # P&L line
        fig.add_trace(go.Scatter(
            x=spot_range, y=pnl, mode="lines",
            name="P&L at Expiry",
            line=dict(color="#2962ff", width=2.5),
            hovertemplate="Spot: %{x:,.0f}<br>P&L: ₹%{y:,.2f}<extra></extra>"))
        # Current spot line
        fig.add_vline(x=spot, line=dict(color="#787b86", width=1, dash="dash"),
                      annotation_text=f"Spot {spot:,.0f}",
                      annotation_font=dict(color="#787b86", size=10))
        # Breakeven lines
        for be in breakevens:
            fig.add_vline(x=be, line=dict(color="#ff9800", width=1, dash="dot"),
                          annotation_text=f"BE {be:,.0f}",
                          annotation_font=dict(color="#ff9800", size=9))
        fig.add_hline(y=0, line=dict(color="#363a45", width=1))

        fig.update_layout(
            title=dict(text=f"Strategy Payoff — {index} {r['expiry']}",
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

        # ── Summary chips ──────────────────────────────────────────────────────
        chips = [
            ("Net Premium",  f"₹{net_prem:+,.2f}",  "#d1d4dc"),
            ("Max Profit",   "Unlimited" if max_profit>1e6 else f"₹{max_profit:,.0f}", "#26a69a"),
            ("Max Loss",     f"₹{max_loss:,.0f}",    "#ef5350"),
            ("Breakevens",   " / ".join([f"{b:,.0f}" for b in breakevens]) or "—", "#ff9800"),
        ]
        for col,(lbl,val,clr) in zip(st.columns(4), chips):
            with col:
                st.markdown(f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                            f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                            unsafe_allow_html=True)

        # ── Greeks ─────────────────────────────────────────────────────────────
        st.markdown('<div class="sec-header" style="margin-top:12px;">Net Greeks</div>',
                    unsafe_allow_html=True)
        net_g = _strategy_greeks(legs, spot)
        for col,(lbl,key,clr) in zip(st.columns(5),[
            ("Net Delta","delta","#2962ff"),("Net Gamma","gamma","#ff9800"),
            ("Net Vega","vega","#9c27b0"),("Net Theta","theta","#ef5350"),
            ("Net IV","net_iv","#26a69a")
        ]):
            with col:
                val = f"{net_g[key]:+.4f}" if key!="net_iv" else f"{net_g[key]:.2f}%"
                st.markdown(f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                            f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                            unsafe_allow_html=True)

        # ── P&L simulation at different spot levels ────────────────────────────
        st.markdown('<div class="sec-header" style="margin-top:12px;">P&L Simulation</div>',
                    unsafe_allow_html=True)
        sim_spots = [spot*(1+x/100) for x in [-10,-8,-5,-3,-2,-1,0,1,2,3,5,8,10]]
        sim_pnl   = _payoff_at_expiry(legs, np.array(sim_spots))
        sim_df    = pd.DataFrame({
            "Spot Price":  [f"{s:,.0f}" for s in sim_spots],
            "Change %":    [f"{(s/spot-1)*100:+.1f}%" for s in sim_spots],
            "P&L (₹)":     [f"₹{p:,.2f}" for p in sim_pnl],
        })
        st.dataframe(sim_df, use_container_width=True, hide_index=True)

        # ── Leg summary table ──────────────────────────────────────────────────
        st.markdown('<div class="sec-header" style="margin-top:8px;">Leg Summary</div>',
                    unsafe_allow_html=True)
        leg_rows = []
        for i,l in enumerate(legs):
            sign = 1 if l["bs"]=="Buy" else -1
            try:
                sig  = implied_volatility(l["premium"], spot, l["strike"],
                                           l["T"], RISK_FREE_RATE, l["cp"])
                g    = bs_greeks(spot, l["strike"], l["T"], RISK_FREE_RATE, sig, l["cp"])
                iv_  = round(sig*100,1)
                d_   = round(sign*l["qty"]*g["delta"],3)
                t_   = round(sign*l["qty"]*g["theta"],2)
            except Exception:
                iv_ = d_ = t_ = "—"
            leg_rows.append({
                "Leg": f"L{i+1}", "B/S": l["bs"], "Type": l["cp"],
                "Strike": l["strike"], "Qty": l["qty"],
                "Premium": l["premium"], "IV%": iv_,
                "Net Δ": d_, "Net θ": t_,
            })
        st.dataframe(pd.DataFrame(leg_rows), use_container_width=True, hide_index=True)
