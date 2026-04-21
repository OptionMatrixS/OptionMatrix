"""
strategy_builder.py — Multi-leg Strategy Builder
Sensibull-style payoff chart, Greeks, P&L simulation.
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
    bs_greeks, implied_volatility, RISK_FREE_RATE, _dte
)

_SS = st.session_state
INDICES = ["NIFTY","SENSEX","BANKNIFTY","FINNIFTY"]
LOT_SIZE = {"NIFTY":75,"SENSEX":20,"BANKNIFTY":35,"FINNIFTY":40}

PRESETS = {
    "Custom":[],
    "Bull Call Spread":   [("Buy","CE",0),("Sell","CE",1)],
    "Bear Put Spread":    [("Buy","PE",1),("Sell","PE",0)],
    "Long Straddle":      [("Buy","CE",0),("Buy","PE",0)],
    "Short Straddle":     [("Sell","CE",0),("Sell","PE",0)],
    "Long Strangle":      [("Buy","CE",1),("Buy","PE",-1)],
    "Short Strangle":     [("Sell","CE",1),("Sell","PE",-1)],
    "Iron Condor":        [("Buy","PE",-2),("Sell","PE",-1),("Sell","CE",1),("Buy","CE",2)],
    "Bull Put Spread":    [("Sell","PE",0),("Buy","PE",-1)],
    "Bear Call Spread":   [("Sell","CE",0),("Buy","CE",1)],
}

def _init():
    for k,v in [("sb_n_legs",2),("sb_result",None),("sb_preset","Custom")]:
        if k not in _SS: _SS[k]=v

def _pnl_at_expiry(legs, spot_arr):
    pnl = np.zeros(len(spot_arr))
    for leg in legs:
        K=leg["strike"]; cp=leg["cp"]
        qty=leg["qty"]; sign=1 if leg["bs"]=="Buy" else -1
        prem=leg["premium"]
        intrinsic=(np.maximum(spot_arr-K,0) if cp=="CE" else np.maximum(K-spot_arr,0))
        pnl += sign*(intrinsic-prem)*qty
    return pnl

def _net_greeks(legs):
    net={"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"ivs":[]}
    for leg in legs:
        try:
            S=get_spot_price(leg["index"]); K=leg["strike"]; cp=leg["cp"]
            T=leg.get("T",30/365); prem=leg["premium"]
            sig=implied_volatility(prem,S,K,T,RISK_FREE_RATE,cp)
            g=bs_greeks(S,K,T,RISK_FREE_RATE,sig,cp)
            sgn=1 if leg["bs"]=="Buy" else -1; qty=leg["qty"]
            for k in("delta","gamma","vega","theta"): net[k]+=sgn*qty*g[k]
            net["ivs"].append(g["iv"])
        except: pass
    return {k:round(v,4) for k,v in {**net,"net_iv":round(sum(net["ivs"])/len(net["ivs"]),2) if net["ivs"] else 0.}.items() if k!="ivs"}

def render():
    _init()
    st.markdown('<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">🏗️ Strategy Builder</div>',unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#787b86;margin-bottom:12px;">Multi-leg · Payoff chart · Greeks · P&L simulation</div>',unsafe_allow_html=True)

    # Lot size reference
    st.markdown(
        '<div style="font-size:11px;color:#787b86;padding:6px 10px;background:#1e222d;'
        'border:1px solid #2a2e39;border-radius:5px;margin-bottom:10px;">' +
        " &nbsp;|&nbsp; ".join([f"<b style='color:#d1d4dc;'>{k}</b> = {v} shares/lot"
                                 for k,v in LOT_SIZE.items()]) + '</div>',
        unsafe_allow_html=True)

    # ── Top controls ──────────────────────────────────────────────────────────
    c1,c2,c3 = st.columns(3)
    with c1:
        n_legs = st.selectbox("Number of Legs", list(range(2,11)),
                               index=_SS.sb_n_legs-2, key="sb_n_legs_sel")
        _SS.sb_n_legs = n_legs
    with c2:
        preset = st.selectbox("Strategy Preset", list(PRESETS.keys()), key="sb_preset")
    with c3:
        refresh = st.button("🔄 Refresh Prices", use_container_width=True,
                             help="Re-fetch all live premiums")

    preset_defs = PRESETS.get(preset,[])
    st.markdown('<div class="sec-header" style="margin-top:8px;">Configure Legs</div>',unsafe_allow_html=True)

    # ── Leg inputs ────────────────────────────────────────────────────────────
    legs_input = []
    for i in range(n_legs):
        p_bs = preset_defs[i][0] if i<len(preset_defs) else ("Buy" if i%2==0 else "Sell")
        p_cp = preset_defs[i][1] if i<len(preset_defs) else "CE"
        p_off= preset_defs[i][2] if i<len(preset_defs) else 0
        color= ["#2962ff","#26a69a","#ff9800","#ef5350","#9c27b0",
                "#00bcd4","#8bc34a","#ff5722","#607d8b","#e91e63"][i%10]

        st.markdown(
            f'<div style="font-size:10px;color:{color};font-weight:700;'
            f'background:#1e222d;padding:3px 10px;border-left:3px solid {color};'
            f'border-radius:3px;margin-top:8px;">LEG {i+1}</div>',
            unsafe_allow_html=True)

        lc = st.columns([1,1,1,1,1,1,1])

        with lc[0]:
            leg_idx = st.selectbox("Index", INDICES, key=f"sb_idx_{i}")
        with lc[1]:
            try:
                exps = get_expiries(leg_idx)
                leg_exp = st.selectbox("Expiry", exps, key=f"sb_exp_{i}")
            except Exception as e:
                st.error(f"Expiry:{e}"); legs_input.append(None); continue
        with lc[2]:
            bs = st.selectbox("B/S",["Buy","Sell"], key=f"sb_bs_{i}",
                              index=0 if p_bs=="Buy" else 1)
        with lc[3]:
            cp = st.selectbox("CE/PE",["CE","PE"], key=f"sb_cp_{i}",
                              index=0 if p_cp=="CE" else 1)
        with lc[4]:
            try:
                leg_strikes = get_strikes(leg_idx, leg_exp)
            except:
                atm_={"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(leg_idx,22800)
                step_=50 if leg_idx=="NIFTY" else(100 if leg_idx=="BANKNIFTY" else 500)
                leg_strikes=list(range(atm_-40*step_,atm_+41*step_,step_))
            # Default to ATM + preset offset
            try: spot_=get_spot_price(leg_idx)
            except: spot_={"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(leg_idx,22800)
            atm_leg=min(leg_strikes,key=lambda x:abs(x-spot_)) if leg_strikes else spot_
            step_leg=(leg_strikes[1]-leg_strikes[0]) if len(leg_strikes)>1 else 50
            def_stk=min(leg_strikes,key=lambda x:abs(x-(atm_leg+p_off*step_leg))) if leg_strikes else atm_leg
            cur=_SS.get(f"sb_strike_{i}",def_stk)
            sidx=leg_strikes.index(cur) if cur in leg_strikes else (leg_strikes.index(def_stk) if def_stk in leg_strikes else 0)
            strike=st.selectbox("Strike",leg_strikes,index=sidx,key=f"sb_strike_{i}")
        with lc[5]:
            lots=st.number_input(f"Lots",min_value=1,max_value=100,value=1,key=f"sb_lots_{i}")
            qty=lots*LOT_SIZE.get(leg_idx,1)
        with lc[6]:
            # Auto-fetch premium
            if refresh or _SS.get(f"sb_prem_{i}",0)==0:
                try: live_p=get_live_ltp(leg_idx,strike,leg_exp,cp)
                except: live_p=0.0
                _SS[f"sb_prem_{i}"]=float(round(live_p,2))
            prem=st.number_input("Premium ₹",min_value=0.0,
                                  value=float(_SS.get(f"sb_prem_{i}",0.0)),
                                  step=0.5,key=f"sb_prem_inp_{i}",
                                  help="Auto-fetched. Edit to override.")
            _SS[f"sb_prem_{i}"]=prem

        T=_dte(leg_exp,leg_idx)
        # Show IV + delta below row
        try:
            iv=implied_volatility(prem,spot_,strike,T,RISK_FREE_RATE,cp)*100
            g=bs_greeks(spot_,strike,T,RISK_FREE_RATE,iv/100 if iv>0 else 0.2,cp)
            sgn=1 if bs=="Buy" else -1
            st.markdown(
                f'<div style="font-size:10px;color:#787b86;margin-top:1px;">'
                f'IV:<span style="color:#ff9800;"> {iv:.1f}%</span> &nbsp; '
                f'Δ:<span style="color:#2962ff;"> {sgn*g["delta"]:+.3f}</span> &nbsp; '
                f'Qty:<span style="color:#d1d4dc;"> {qty}</span></div>',
                unsafe_allow_html=True)
        except: pass

        legs_input.append(dict(bs=bs,cp=cp,strike=strike,qty=qty,lots=lots,
                               premium=prem,T=T,index=leg_idx,expiry=leg_exp))

    valid_legs = [l for l in legs_input if l is not None and l["strike"]>0 and l["expiry"]]

    # ── Build button ──────────────────────────────────────────────────────────
    st.markdown('<div style="height:6px"></div>',unsafe_allow_html=True)
    if st.button("📊  Build Payoff Chart", type="primary", use_container_width=False, key="sb_calc"):
        if not valid_legs:
            st.error("No valid legs. Check all selections."); return
        # Compute spot for payoff range (use first leg's index)
        try: ref_spot=get_spot_price(valid_legs[0]["index"])
        except: ref_spot=valid_legs[0]["strike"]
        _SS.sb_result={"legs":valid_legs,"ref_spot":ref_spot}
        st.rerun()

    if st.button("🗑️ Clear Chart", key="sb_clear"):
        _SS.sb_result=None; st.rerun()

    # ── Output section ────────────────────────────────────────────────────────
    if not _SS.sb_result:
        st.markdown('<div style="height:200px;display:flex;align-items:center;justify-content:center;'
                    'background:#1e222d;border:1px dashed #2a2e39;border-radius:8px;margin-top:12px;">'
                    '<div style="text-align:center;color:#787b86;">'
                    '<div style="font-size:24px;margin-bottom:8px;">📊</div>'
                    'Configure legs above and click Build Payoff Chart</div></div>',
                    unsafe_allow_html=True)
        return

    r=_SS.sb_result; legs=r["legs"]; ref_spot=r["ref_spot"]

    # Payoff range ±20% of reference spot
    lo=ref_spot*0.80; hi=ref_spot*1.20
    spot_arr=np.linspace(lo,hi,400)
    pnl=_pnl_at_expiry(legs,spot_arr)

    net_prem=sum((-1 if l["bs"]=="Buy" else 1)*l["premium"]*l["qty"] for l in legs)
    max_profit=float(pnl.max()); max_loss=float(pnl.min())
    beidx=np.where(np.diff(np.sign(pnl)))[0]
    bes=[round(float(spot_arr[i]),0) for i in beidx]

    # ── Payoff chart ──────────────────────────────────────────────────────────
    fig=go.Figure()
    fig.add_trace(go.Scatter(x=spot_arr,y=np.where(pnl>=0,pnl,0),fill="tozeroy",
        fillcolor="rgba(38,166,154,0.12)",line=dict(width=0),showlegend=False,hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=spot_arr,y=np.where(pnl<=0,pnl,0),fill="tozeroy",
        fillcolor="rgba(239,83,80,0.12)",line=dict(width=0),showlegend=False,hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=spot_arr,y=pnl,mode="lines",name="P&L at Expiry",
        line=dict(color="#2962ff",width=2.5),
        hovertemplate="Spot:%{x:,.0f}<br>P&L:₹%{y:,.0f}<extra></extra>"))
    fig.add_vline(x=ref_spot,line=dict(color="#787b86",width=1,dash="dash"),
                  annotation_text=f"Spot {ref_spot:,.0f}",
                  annotation_font=dict(color="#787b86",size=10))
    for be in bes:
        fig.add_vline(x=be,line=dict(color="#ff9800",width=1,dash="dot"),
                      annotation_text=f"BE {be:,.0f}",
                      annotation_font=dict(color="#ff9800",size=9))
    fig.add_hline(y=0,line=dict(color="#363a45",width=1))
    title_parts=[f"{l['index']} {l['strike']}{l['cp']} {l['bs'][0]}" for l in legs]
    fig.update_layout(
        title=dict(text=" | ".join(title_parts),font=dict(size=11,color="#d1d4dc"),x=0),
        paper_bgcolor="#131722",plot_bgcolor="#131722",
        xaxis=dict(gridcolor="#1e222d",tickfont=dict(size=10,color="#787b86"),
                   showline=False,zeroline=False,
                   title=dict(text="Underlying Price",font=dict(color="#787b86",size=10))),
        yaxis=dict(gridcolor="#1e222d",tickfont=dict(size=10,color="#787b86"),
                   showline=False,zeroline=False,side="right",
                   title=dict(text="P&L (₹)",font=dict(color="#787b86",size=10))),
        margin=dict(l=10,r=80,t=40,b=40),height=420,
        hovermode="x unified",dragmode="pan",
        hoverlabel=dict(bgcolor="#1e222d",bordercolor="#2a2e39",font=dict(size=11,color="#d1d4dc")))
    st.plotly_chart(fig,use_container_width=True,config={"scrollZoom":True,"displaylogo":False})

    # Summary chips
    for col,(lbl,val,clr) in zip(st.columns(4),[
        ("Net Premium",f"₹{net_prem:+,.0f}","#d1d4dc"),
        ("Max Profit","Unlimited" if max_profit>1e6 else f"₹{max_profit:,.0f}","#26a69a"),
        ("Max Loss",f"₹{max_loss:,.0f}","#ef5350"),
        ("Breakevens"," / ".join([f"{b:,.0f}" for b in bes]) or "—","#ff9800"),
    ]):
        with col:
            st.markdown(f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                        f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                        unsafe_allow_html=True)

    # Net Greeks
    st.markdown('<div class="sec-header" style="margin-top:12px;">Net Greeks</div>',unsafe_allow_html=True)
    ng=_net_greeks(legs)
    for col,(lbl,k,clr) in zip(st.columns(5),[
        ("Net Δ","delta","#2962ff"),("Net Γ","gamma","#ff9800"),
        ("Net V","vega","#9c27b0"),("Net θ","theta","#ef5350"),
        ("Net IV","net_iv","#26a69a")
    ]):
        with col:
            val=f"{ng[k]:+.4f}" if k!="net_iv" else f"{ng[k]:.2f}%"
            st.markdown(f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                        f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                        unsafe_allow_html=True)

    # P&L simulation
    st.markdown('<div class="sec-header" style="margin-top:12px;">P&L Simulation</div>',unsafe_allow_html=True)
    moves=[-10,-8,-5,-3,-2,-1,0,1,2,3,5,8,10]
    sim_s=np.array([ref_spot*(1+m/100) for m in moves])
    sim_p=_pnl_at_expiry(legs,sim_s)
    sim_df=pd.DataFrame({
        "Move %":[f"{m:+d}%" for m in moves],
        "Spot":[f"{s:,.0f}" for s in sim_s],
        "P&L":[f"₹{p:+,.0f}" for p in sim_p],
        "Status":["✅ Profit" if p>0 else "❌ Loss" if p<0 else "⚪ Break-even" for p in sim_p]
    })
    st.dataframe(sim_df,use_container_width=True,hide_index=True,height=320)

    # Leg summary
    st.markdown('<div class="sec-header" style="margin-top:8px;">Leg Summary</div>',unsafe_allow_html=True)
    leg_tbl=[]
    for i,l in enumerate(legs):
        sgn=1 if l["bs"]=="Buy" else -1
        try:
            S=get_spot_price(l["index"])
            sig=implied_volatility(l["premium"],S,l["strike"],l["T"],RISK_FREE_RATE,l["cp"])
            g=bs_greeks(S,l["strike"],l["T"],RISK_FREE_RATE,sig,l["cp"])
            iv_=f"{sig*100:.1f}%"; d_=f"{sgn*l['qty']*g['delta']:+.3f}"; t_=f"{sgn*l['qty']*g['theta']:+.2f}"
        except: iv_=d_=t_="—"
        leg_tbl.append({"Leg":f"L{i+1}","Index":l["index"],"B/S":l["bs"],"CE/PE":l["cp"],
                        "Strike":l["strike"],"Lots":l["lots"],"Qty":l["qty"],
                        "Premium":l["premium"],"IV":iv_,"Net Δ":d_,"Net θ":t_})
    st.dataframe(pd.DataFrame(leg_tbl),use_container_width=True,hide_index=True)
