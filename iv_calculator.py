import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import plotly.graph_objects as go
from data_helpers import get_index_expiries, get_index_strikes, get_iv_series, TF_MAP

_SS = st.session_state
EXPIRY_COLORS = ["#2962ff","#26a69a","#ff9800","#ef5350","#9c27b0"]
EXPIRY_DASH   = ["solid","solid","dash","dash","dot"]

def render():
    if "iv_result" not in _SS: _SS.iv_result = None

    st.markdown('<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">🌡️ IV Calculator</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#787b86;margin-bottom:16px;">Implied Volatility — Black-Scholes. Up to 5 expiries.</div>', unsafe_allow_html=True)

    ctrl_col, chart_col = st.columns([1, 2.5], gap="medium")

    with ctrl_col:
        st.markdown('<div class="sec-header">Parameters</div>', unsafe_allow_html=True)
        idx = st.selectbox("Index",["NIFTY","SENSEX","BANKNIFTY"],key="iv_idx")
        try:
            exps = get_index_expiries(idx)
        except Exception as e:
            st.error(f"Load expiries failed: {e}"); return
        if not exps: exps = ["—"]
        strikes = get_index_strikes(idx, exps[0]) if exps[0]!="—" else []
        if not strikes: strikes = [22800]
        atm   = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx,22800)
        def_s = min(strikes, key=lambda x: abs(x-atm))
        strike = st.selectbox("Strike",strikes,index=strikes.index(def_s),key="iv_strike")
        cp     = st.selectbox("CE / PE",["CE","PE"],key="iv_cp")
        tf     = st.selectbox("Timeframe",list(TF_MAP.keys()),index=1,key="iv_tf")
        n_exp  = st.selectbox("Number of expiries (1–5)",list(range(1,6)),key="iv_nexp")

        st.markdown('<div class="sec-header" style="margin-top:8px;">Select Expiries</div>', unsafe_allow_html=True)
        selected = []
        for i in range(n_exp):
            e = st.selectbox(f"Expiry {i+1}",exps,index=min(i,len(exps)-1),key=f"iv_exp_{i}")
            selected.append(e)

        if st.button("📈  Calculate IV",use_container_width=True,type="primary"):
            with st.spinner("Fetching live IV data…"):
                try:
                    series = {exp: get_iv_series(idx,strike,exp,cp,tf_minutes=TF_MAP[tf]) for exp in selected}
                    _SS.iv_result = dict(index=idx,strike=strike,cp=cp,tf=tf,expiries=selected,series=series)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        if _SS.iv_result:
            r = _SS.iv_result
            st.markdown("---")
            for i,exp in enumerate(r["expiries"]):
                df     = r["series"][exp]
                latest = df["iv_pct"].iloc[-1]
                color  = EXPIRY_COLORS[i%len(EXPIRY_COLORS)]
                st.markdown(f'<div style="background:#1e222d;border:1px solid #2a2e39;border-left:3px solid {color};'
                            f'border-radius:5px;padding:8px 12px;margin-bottom:5px;">'
                            f'<div style="font-size:10px;color:#787b86;">{exp}</div>'
                            f'<div style="font-size:18px;font-weight:500;color:{color};">{latest:.2f}%</div></div>',
                            unsafe_allow_html=True)

    with chart_col:
        if not _SS.iv_result:
            st.markdown('<div style="height:420px;display:flex;align-items:center;justify-content:center;'
                        'background:#1e222d;border:1px solid #2a2e39;border-radius:8px;">'
                        '<div style="font-size:14px;color:#787b86;">Configure and click Calculate IV</div></div>',
                        unsafe_allow_html=True); return
        r   = _SS.iv_result
        fig = go.Figure()
        for i,exp in enumerate(r["expiries"]):
            df     = r["series"][exp]
            color  = EXPIRY_COLORS[i%len(EXPIRY_COLORS)]
            dash   = EXPIRY_DASH[i%len(EXPIRY_DASH)]
            latest = df["iv_pct"].iloc[-1]
            fig.add_trace(go.Scatter(x=df["time"],y=df["iv_pct"],mode="lines",
                name=f"{exp}  {latest:.2f}%",line=dict(color=color,width=1.8,dash=dash),
                hovertemplate=f"<b>{exp}</b><br>IV: %{{y:.2f}}%<extra></extra>"))
            fig.add_annotation(x=df["time"].iloc[-1],y=latest,text=f" {latest:.2f}%",
                showarrow=False,font=dict(size=10,color="#fff"),bgcolor=color,borderpad=3,xanchor="left")
        fig.add_hrect(y0=10,y1=25,fillcolor="#2962ff",opacity=0.04,line_width=0,
                      annotation_text="Normal IV zone",annotation_font=dict(size=9,color="#787b86"),
                      annotation_position="bottom right")
        title = f"{r['index']} {r['strike']} {r['cp']} — Implied Volatility [{r['tf']}]"
        fig.update_layout(title=dict(text=title,font=dict(size=12,color="#d1d4dc"),x=0),
            paper_bgcolor="#131722",plot_bgcolor="#131722",
            xaxis=dict(gridcolor="#1e222d",tickfont=dict(size=10,color="#787b86"),showline=False,zeroline=False,fixedrange=False),
            yaxis=dict(gridcolor="#1e222d",tickfont=dict(size=10,color="#787b86"),showline=False,zeroline=False,
                       side="right",fixedrange=False,title=dict(text="IV %"),ticksuffix="%"),
            legend=dict(font=dict(size=11,color="#d1d4dc"),bgcolor="#1e222d",bordercolor="#2a2e39",borderwidth=1),
            margin=dict(l=10,r=72,t=40,b=28),height=420,hovermode="x unified",dragmode="pan",
            hoverlabel=dict(bgcolor="#1e222d",bordercolor="#2a2e39",font=dict(size=11,color="#d1d4dc")))
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":True,"displaylogo":False,"scrollZoom":True})

        cols = st.columns(len(r["expiries"]))
        for col,(exp,color) in zip(cols,zip(r["expiries"],[EXPIRY_COLORS[i] for i in range(len(r["expiries"]))])):
            df = r["series"][exp]; iv = df["iv_pct"]
            with col:
                st.markdown(f'<div class="stat-chip" style="border-left:3px solid {color};">'
                            f'<div class="sc-label">{exp}</div>'
                            f'<div class="sc-val" style="color:{color};">{iv.iloc[-1]:.2f}%</div>'
                            f'<div style="font-size:10px;color:#787b86;margin-top:4px;">H:{iv.max():.2f}% L:{iv.min():.2f}%</div></div>',
                            unsafe_allow_html=True)
