import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import plotly.graph_objects as go
from data_helpers import get_multiplier_series, get_nifty_expiries, get_sensex_expiries, get_nifty_strikes, get_sensex_strikes, TF_MAP

_SS = st.session_state

def _init():
    for k,v in [("mx_result",None)]:
        if k not in _SS: _SS[k] = v

def render():
    _init()
    st.markdown('<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:8px;">✖️ Multiplier Chart</div>',
                unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;color:#787b86;margin-bottom:16px;">'
                'Tracks: <code style="color:#2962ff;background:#1e222d;padding:1px 5px;border-radius:3px;">'
                '(SX_strike + SX_CE − SX_PE) ÷ (N_strike + N_CE − N_PE)</code></div>',
                unsafe_allow_html=True)

    ctrl_col, chart_col = st.columns([1, 2.5], gap="medium")

    with ctrl_col:
        st.markdown('<div class="sec-header">SENSEX (BSE)</div>', unsafe_allow_html=True)
        sx_exps = get_sensex_expiries()
        if not sx_exps: sx_exps = ["—"]
        sx_exp = st.selectbox("SENSEX Expiry", sx_exps, key="mx_sx_exp")
        sx_strikes = get_sensex_strikes(sx_exp)
        if not sx_strikes: sx_strikes = [82000]
        sx_def = min(sx_strikes, key=lambda x: abs(x-82500))
        sx_strike = st.selectbox("SENSEX Strike", sx_strikes,
                                  index=sx_strikes.index(sx_def), key="mx_sx_str")

        st.markdown('<div class="sec-header" style="margin-top:12px;">NIFTY (NSE)</div>',
                    unsafe_allow_html=True)
        n_exps = get_nifty_expiries()
        if not n_exps: n_exps = ["—"]
        n_exp = st.selectbox("NIFTY Expiry", n_exps, key="mx_n_exp")
        n_strikes = get_nifty_strikes(n_exp)
        if not n_strikes: n_strikes = [22800]
        n_def = min(n_strikes, key=lambda x: abs(x-22800))
        n_strike = st.selectbox("NIFTY Strike", n_strikes,
                                 index=n_strikes.index(n_def), key="mx_n_str")

        tf = st.selectbox("Timeframe", list(TF_MAP.keys()), key="mx_tf")

        if st.button("📡  Plot Multiplier", use_container_width=True, type="primary"):
            with st.spinner("Fetching live data..."):
                try:
                    df = get_multiplier_series(sx_strike, sx_exp, n_strike, n_exp,
                                               tf_minutes=TF_MAP[tf])
                    _SS.mx_result = dict(df=df, sx_strike=sx_strike, sx_exp=sx_exp,
                                         n_strike=n_strike, n_exp=n_exp, tf=tf)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        if _SS.mx_result:
            df   = _SS.mx_result["df"]
            last = df["multiplier"].iloc[-1]
            avg  = df["multiplier"].mean()
            hi   = df["multiplier"].max()
            lo   = df["multiplier"].min()
            chg  = last - df["multiplier"].iloc[0]
            st.markdown("---")
            for label,val,color in [
                ("Multiplier", f"{last:.4f}", "#26a69a" if chg>=0 else "#ef5350"),
                ("Change",     f"{chg:+.4f}", "#26a69a" if chg>=0 else "#ef5350"),
                ("Average",    f"{avg:.4f}",  "#d1d4dc"),
                ("High",       f"{hi:.4f}",   "#26a69a"),
                ("Low",        f"{lo:.4f}",   "#ef5350"),
            ]:
                st.markdown(
                    f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:5px;'
                    f'padding:7px 12px;margin-bottom:4px;display:flex;justify-content:space-between;">'
                    f'<span style="font-size:11px;color:#787b86;">{label}</span>'
                    f'<span style="font-size:12px;font-weight:500;color:{color};'
                    f'font-family:\'JetBrains Mono\',monospace;">{val}</span></div>',
                    unsafe_allow_html=True)

    with chart_col:
        if not _SS.mx_result:
            st.markdown('<div style="height:480px;display:flex;align-items:center;justify-content:center;'
                        'background:#1e222d;border:1px solid #2a2e39;border-radius:8px;">'
                        '<div style="text-align:center;font-size:14px;color:#787b86;">Configure and click Plot Multiplier</div>'
                        '</div>', unsafe_allow_html=True)
            return

        r    = _SS.mx_result
        df   = r["df"]
        last = df["multiplier"].iloc[-1]
        first= df["multiplier"].iloc[0]
        lc   = "#26a69a" if last>=first else "#ef5350"
        avg  = df["multiplier"].mean()

        fig = go.Figure()
        fig.add_hline(y=avg, line=dict(color="#787b86",width=1,dash="dash"),
                      annotation_text=f"Avg {avg:.4f}",
                      annotation_font=dict(size=10,color="#787b86"),
                      annotation_position="right")
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["multiplier"], mode="lines", name="Multiplier",
            line=dict(color=lc, width=2),
            fill="tozeroy", fillcolor=f"rgba({'38,166,154' if lc=='#26a69a' else '239,83,80'},0.07)"))
        fig.add_annotation(x=df["time"].iloc[-1], y=last,
            text=f" {last:.4f}", showarrow=False,
            font=dict(size=11,color="#fff",family="JetBrains Mono"),
            bgcolor=lc, borderpad=4, xanchor="left")

        title = (f"SENSEX {r['sx_strike']} ({r['sx_exp']}) / "
                 f"NIFTY {r['n_strike']} ({r['n_exp']}) — Multiplier [{r['tf']}]")
        fig.update_layout(
            title=dict(text=title, font=dict(size=12,color="#d1d4dc"), x=0),
            paper_bgcolor="#131722", plot_bgcolor="#131722",
            xaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10,color="#787b86",family="JetBrains Mono"),
                       rangeslider=dict(visible=False), showline=False, zeroline=False, fixedrange=False),
            yaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10,color="#787b86",family="JetBrains Mono"),
                       showline=False, zeroline=False, side="right", fixedrange=False),
            legend=dict(font=dict(size=11,color="#787b86"),bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=10,r=80,t=40,b=28), height=400,
            hovermode="x unified", dragmode="pan",
            hoverlabel=dict(bgcolor="#1e222d",bordercolor="#2a2e39",
                            font=dict(size=11,color="#d1d4dc",family="JetBrains Mono")))
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar":True,"displaylogo":False,"scrollZoom":True})

        # Synthetic sub-chart
        st.markdown('<div class="sec-header" style="margin-top:8px;">Synthetic Spot</div>',
                    unsafe_allow_html=True)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["time"], y=df["sx_synth"], mode="lines",
            name="SENSEX Synthetic", line=dict(color="#4caf50",width=1.5), yaxis="y1"))
        fig2.add_trace(go.Scatter(x=df["time"], y=df["n_synth"], mode="lines",
            name="NIFTY Synthetic", line=dict(color="#9c27b0",width=1.5,dash="dash"), yaxis="y2"))
        fig2.update_layout(
            paper_bgcolor="#131722", plot_bgcolor="#131722",
            xaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10,color="#787b86",family="JetBrains Mono"),
                       showline=False, zeroline=False),
            yaxis=dict(side="left", tickfont=dict(size=9,color="#4caf50",family="JetBrains Mono"),
                       showline=False, zeroline=False, gridcolor="#1e222d",
                       title=dict(text="SENSEX",font=dict(size=10,color="#4caf50"))),
            yaxis2=dict(overlaying="y", side="right",
                        tickfont=dict(size=9,color="#9c27b0",family="JetBrains Mono"),
                        showline=False, zeroline=False,
                        title=dict(text="NIFTY",font=dict(size=10,color="#9c27b0"))),
            legend=dict(font=dict(size=11,color="#d1d4dc"),bgcolor="#1e222d",
                        bordercolor="#2a2e39",borderwidth=1,x=0.01,y=0.99),
            margin=dict(l=10,r=80,t=10,b=28), height=200, hovermode="x unified",
            hoverlabel=dict(bgcolor="#1e222d",bordercolor="#2a2e39",
                            font=dict(size=11,color="#d1d4dc",family="JetBrains Mono")))
        st.plotly_chart(fig2, use_container_width=True,
                        config={"displayModeBar":False,"displaylogo":False})
