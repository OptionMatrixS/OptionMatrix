import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in [_ROOT, _HERE]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

"""pages/spread_chart.py — Spread Chart Builder with TradingView-style scroll/zoom"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from data_helpers import (
    NIFTY_STRIKES, SENSEX_STRIKES, NIFTY_EXPIRIES, SENSEX_EXPIRIES,
    get_option_price, generate_spread_ohlcv, TF_MAP
)

_SS = st.session_state

def _init():
    defaults = {
        "sp_n_legs": 2,
        "sp_chart_type": "Candlestick",
        "sp_tf": "1m",
        "sp_result": None,
        "sp_df": None,
        "sp_legs_live": [],   # persists across page switches
    }
    for k, v in defaults.items():
        if k not in _SS:
            _SS[k] = v

def _build_chart(df, result, chart_type, tf):
    title = "SPREAD CHART"
    if result:
        legs = result["legs"]
        if len(legs) >= 2:
            l1, l2 = legs[0], legs[1]
            title = (f"{l1['index']} {l1['strike']}{l1['cp']} {l1['bs'][0]}"
                     f" / {l2['index']} {l2['strike']}{l2['cp']} {l2['bs'][0]}"
                     f"  [{tf}]")

    fig = go.Figure()
    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=df["time"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="Spread",
            increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
            line=dict(width=1), whiskerwidth=0.3,
        ))
    else:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["close"], mode="lines", name="Spread",
            line=dict(color="#2962ff", width=1.5),
            fill="tozeroy", fillcolor="rgba(41,98,255,0.07)",
        ))

    fig.add_hline(y=0, line=dict(color="#363a45", width=1, dash="dot"))
    last = df["close"].iloc[-1]
    fig.add_annotation(
        x=df["time"].iloc[-1], y=last,
        text=f" {last:.2f}", showarrow=False,
        font=dict(size=11, color="#fff", family="JetBrains Mono"),
        bgcolor="#26a69a" if last >= 0 else "#ef5350",
        borderpad=4, xanchor="left",
    )
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#d1d4dc", family="IBM Plex Sans"), x=0, xref="paper"),
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        xaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                   tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                   rangeslider=dict(visible=False), showline=False, zeroline=False,
                   fixedrange=False, type="date"),
        yaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                   tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                   showline=False, zeroline=False, side="right", fixedrange=False),
        legend=dict(font=dict(size=11, color="#787b86"), bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=68, t=36, b=28), height=420,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                        font=dict(size=11, color="#d1d4dc", family="JetBrains Mono")),
        dragmode="pan",
    )
    return fig

def render():
    _init()

    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
      <div style="font-size:20px;font-weight:600;color:#d1d4dc;">📊 Spread Chart</div>
      <div style="font-size:11px;color:#787b86;padding:3px 10px;background:#1e222d;
                  border:1px solid #2a2e39;border-radius:10px;">NFO / BFO</div>
    </div>
    """, unsafe_allow_html=True)

    chart_col, builder_col = st.columns([3, 2], gap="medium")

    with builder_col:
        st.markdown('<div class="sec-header">Strategy Builder</div>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        with c1:
            n_legs = st.selectbox("Legs", list(range(2, 7)),
                                  index=_SS.sp_n_legs - 2, key="sp_legs_sel")
            _SS.sp_n_legs = n_legs
        with c2:
            _SS.sp_chart_type = st.selectbox("Chart", ["Candlestick", "Line"], key="sp_ct_sel")
        with c3:
            _SS.sp_tf = st.selectbox("TF", list(TF_MAP.keys()), key="sp_tf_sel")

        # ── Build legs — read widget values directly from session state keys ──
        # This way the legs list is always current even after page switches
        legs = []
        for i in range(n_legs):
            st.markdown(
                f'<div style="font-size:10px;color:#787b86;margin:10px 0 5px;">'
                f'<span style="background:#2a2e39;padding:2px 8px;border-radius:10px;'
                f'font-family:\'JetBrains Mono\',monospace;">LEG {i+1}</span></div>',
                unsafe_allow_html=True
            )
            ci1, ci2 = st.columns([1, 2])
            with ci1:
                idx = st.selectbox("Index", ["NIFTY", "SENSEX"],
                                   key=f"sp_idx_{i}", label_visibility="collapsed")
            with ci2:
                strikes = NIFTY_STRIKES if idx == "NIFTY" else SENSEX_STRIKES
                atm = 22800 if idx == "NIFTY" else 82500
                def_s = min(strikes, key=lambda x: abs(x - (atm + 200 if i % 2 == 0 else atm - 200)))
                # keep previously selected strike if index didn't change
                prev_key = f"sp_strike_{i}"
                strike = st.selectbox("Strike", strikes,
                                      index=strikes.index(def_s),
                                      key=prev_key, label_visibility="collapsed")

            ci3, ci4, ci5, ci6 = st.columns(4)
            exps = NIFTY_EXPIRIES if idx == "NIFTY" else SENSEX_EXPIRIES
            with ci3:
                expiry = st.selectbox("Exp", exps, key=f"sp_exp_{i}", label_visibility="collapsed")
            with ci4:
                cp = st.selectbox("C/P", ["CE", "PE"], key=f"sp_cp_{i}", label_visibility="collapsed")
            with ci5:
                bs = st.selectbox("B/S", ["Buy", "Sell"],
                                  index=0 if i % 2 == 0 else 1,
                                  key=f"sp_bs_{i}", label_visibility="collapsed")
            with ci6:
                ratio = st.number_input("Ratio", 1, 10, 1, key=f"sp_ratio_{i}",
                                        label_visibility="collapsed")

            ltp = get_option_price(idx, strike, expiry, cp)
            signed = ltp * ratio if bs == "Buy" else -ltp * ratio
            color = "#26a69a" if signed >= 0 else "#ef5350"
            st.markdown(
                f'<div style="font-size:11px;color:#787b86;margin-top:3px;padding:0 2px;">'
                f'LTP: <span style="color:#d1d4dc;font-family:\'JetBrains Mono\',monospace;">{ltp:.2f}</span>'
                f'&nbsp;&nbsp;Net: <span style="color:{color};font-family:\'JetBrains Mono\',monospace;">{signed:+.2f}</span>'
                f'</div>', unsafe_allow_html=True
            )
            legs.append(dict(index=idx, strike=strike, expiry=expiry,
                             cp=cp, bs=bs, ratio=ratio, ltp=ltp, net=round(signed, 2)))
            if i < n_legs - 1:
                st.markdown('<hr style="margin:6px 0;border-color:#2a2e39;">', unsafe_allow_html=True)

        # ── Always persist legs to session state ──────────────────────────────
        # Store with a stable key so Safety Calculator always has the latest
        _SS.sp_legs_live = legs
        # Also store a copy keyed by n_legs so it survives leg count changes
        _SS[f"sp_legs_snapshot_{n_legs}"] = legs

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # Show sync status for Safety Calculator
        st.markdown(
            f'<div style="font-size:10px;color:#26a69a;margin-bottom:6px;">✓ {n_legs} legs synced to Safety Calculator</div>',
            unsafe_allow_html=True
        )

        if st.button("⚡  Calculate & Plot", use_container_width=True, type="primary"):
            buys  = [l for l in legs if l["bs"] == "Buy"]
            sells = [l for l in legs if l["bs"] == "Sell"]
            spread = (sum(l["ltp"] * l["ratio"] for l in buys)
                      - sum(l["ltp"] * l["ratio"] for l in sells))
            net_prem = sum(l["net"] for l in legs)
            if buys and sells:
                sd = abs(buys[0]["strike"] - sells[0]["strike"])
                max_profit = sd - abs(spread) if sd > abs(spread) else None
                max_loss   = abs(spread)
                be = (buys[0]["strike"] + spread if buys[0]["cp"] == "CE"
                      else buys[0]["strike"] - spread)
            else:
                max_profit = max_loss = be = None

            tf_min = TF_MAP[_SS.sp_tf]
            _SS.sp_df     = generate_spread_ohlcv(spread, n_bars=80, tf_minutes=tf_min)
            _SS.sp_result = dict(spread=round(spread, 2), net_prem=round(net_prem, 2),
                                 max_profit=max_profit, max_loss=max_loss, be=be, legs=legs)
            st.rerun()

        if _SS.sp_result:
            r  = _SS.sp_result
            sv = r["spread"]
            st.markdown("---")
            st.markdown(
                f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:8px;'
                f'padding:14px;text-align:center;margin-bottom:12px;">'
                f'<div style="font-size:10px;color:#787b86;text-transform:uppercase;letter-spacing:.07em;">Spread Value</div>'
                f'<div style="font-size:26px;font-weight:600;color:{"#26a69a" if sv>=0 else "#ef5350"};'
                f'font-family:\'JetBrains Mono\',monospace;">{sv:+.2f}</div>'
                f'</div>', unsafe_allow_html=True
            )
            m1, m2 = st.columns(2)
            m3, m4 = st.columns(2)
            with m1: st.metric("Net Premium", f"{r['net_prem']:+.2f}")
            with m2: st.metric("Breakeven", f"{r['be']:.0f}" if r['be'] else "—")
            mp = r['max_profit']
            with m3: st.metric("Max Profit", "Unlimited" if mp is None else f"{mp:.2f}")
            ml = r['max_loss']
            with m4: st.metric("Max Loss", f"{ml:.2f}" if ml else "—")

            df_legs = pd.DataFrame(r["legs"])[["index","strike","expiry","cp","bs","ratio","ltp","net"]]
            df_legs.columns = ["Index","Strike","Expiry","C/P","B/S","Ratio","LTP","Net"]
            st.dataframe(df_legs, use_container_width=True, hide_index=True)

    with chart_col:
        df  = _SS.sp_df if _SS.sp_df is not None else generate_spread_ohlcv(25, 80)
        fig = _build_chart(df, _SS.sp_result, _SS.sp_chart_type, _SS.sp_tf)
        st.plotly_chart(fig, use_container_width=True,
                        config={
                            "displayModeBar": True,
                            "displaylogo": False,
                            "scrollZoom": True,
                            "modeBarButtonsToAdd": ["drawline", "drawopenpath", "eraseshape"],
                            "modeBarButtonsToRemove": ["autoScale2d", "lasso2d", "select2d"],
                            "toImageButtonOptions": {"format": "png", "filename": "spread_chart"},
                        })

        if _SS.sp_result:
            r  = _SS.sp_result
            sv = r["spread"]
            mp = r["max_profit"]
            ml = r["max_loss"]
            items = [
                ("SPREAD",     f"{sv:+.2f}",                               "#26a69a" if sv >= 0 else "#ef5350"),
                ("NET PREM",   f"{r['net_prem']:+.2f}",                    "#d1d4dc"),
                ("MAX PROFIT", "Unlimited" if mp is None else f"{mp:.2f}", "#26a69a"),
                ("MAX LOSS",   f"{ml:.2f}" if ml else "—",                 "#ef5350"),
                ("BREAKEVEN",  f"{r['be']:.0f}" if r['be'] else "—",       "#d1d4dc"),
            ]
            cols = st.columns(5)
            for col, (label, val, color) in zip(cols, items):
                with col:
                    st.markdown(
                        f'<div class="stat-chip"><div class="sc-label">{label}</div>'
                        f'<div class="sc-val" style="color:{color};">{val}</div></div>',
                        unsafe_allow_html=True
                    )
