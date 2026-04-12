import sys, os
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in [_ROOT, _HERE]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
"""pages/iv_calculator.py — Implied Volatility Calculator (Black-Scholes)"""

import streamlit as st
import plotly.graph_objects as go
from data_helpers import (
    NIFTY_STRIKES, SENSEX_STRIKES, NIFTY_EXPIRIES, SENSEX_EXPIRIES,
    get_iv_series, TF_MAP
)

_SS = st.session_state

# One distinct color per expiry line
EXPIRY_COLORS = ["#2962ff", "#26a69a", "#ff9800", "#ef5350", "#9c27b0"]
EXPIRY_DASH   = ["solid",   "solid",   "dash",    "dash",    "dot"]


def _init():
    defaults = {
        "iv_index": "NIFTY", "iv_n_exp": 1,
        "iv_strike": 22800,  "iv_cp": "CE",
        "iv_tf": "5m",       "iv_result": None,
    }
    for k, v in defaults.items():
        if k not in _SS:
            _SS[k] = v


def render():
    _init()

    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
      <div style="font-size:20px;font-weight:600;color:#d1d4dc;">🌡️ IV Calculator</div>
      <div style="font-size:11px;color:#787b86;padding:3px 10px;background:#1e222d;
                  border:1px solid #2a2e39;border-radius:10px;">Black-Scholes</div>
    </div>
    <div style="font-size:12px;color:#787b86;margin-bottom:16px;">
      Implied Volatility time-series — up to 5 expiries, each as a separate line.
    </div>
    """, unsafe_allow_html=True)

    ctrl_col, chart_col = st.columns([1, 2.5], gap="medium")

    # ══════════════════════════════════
    # CONTROLS
    # ══════════════════════════════════
    with ctrl_col:
        st.markdown('<div class="sec-header">Parameters</div>', unsafe_allow_html=True)

        idx = st.selectbox("Index", ["NIFTY", "SENSEX"], key="iv_idx_sel")
        strikes = NIFTY_STRIKES if idx == "NIFTY" else SENSEX_STRIKES
        atm     = 22800 if idx == "NIFTY" else 82500
        def_s   = min(strikes, key=lambda x: abs(x - atm))

        strike = st.selectbox("Strike", strikes, index=strikes.index(def_s), key="iv_strike_sel")
        cp     = st.selectbox("CE / PE", ["CE", "PE"], key="iv_cp_sel")
        tf     = st.selectbox("Timeframe", list(TF_MAP.keys()), index=1, key="iv_tf_sel")

        n_exp = st.selectbox("Number of expiries (1–5)", list(range(1, 6)),
                             index=0, key="iv_nexp_sel")

        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        st.markdown('<div class="sec-header">Select Expiries</div>', unsafe_allow_html=True)

        exps_available = NIFTY_EXPIRIES if idx == "NIFTY" else SENSEX_EXPIRIES
        selected_expiries = []
        for i in range(n_exp):
            e = st.selectbox(
                f"Expiry {i+1}",
                exps_available,
                index=min(i, len(exps_available)-1),
                key=f"iv_exp_{i}"
            )
            selected_expiries.append(e)

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        if st.button("📈  Calculate IV", use_container_width=True, type="primary"):
            _SS.iv_result = dict(
                index=idx, strike=strike, cp=cp, tf=tf,
                expiries=selected_expiries,
                series={
                    exp: get_iv_series(idx, strike, exp, cp,
                                       n_bars=60, tf_minutes=TF_MAP[tf])
                    for exp in selected_expiries
                }
            )
            st.rerun()

        # ── IV legend ──────────────────────────────────────
        if _SS.iv_result:
            r = _SS.iv_result
            st.markdown("---")
            st.markdown('<div class="sec-header">Live IV (latest)</div>', unsafe_allow_html=True)
            for i, exp in enumerate(r["expiries"]):
                df = r["series"][exp]
                latest_iv = df["iv_pct"].iloc[-1]
                color = EXPIRY_COLORS[i % len(EXPIRY_COLORS)]
                st.markdown(
                    f'<div style="background:#1e222d;border:1px solid #2a2e39;border-left:3px solid {color};'
                    f'border-radius:5px;padding:8px 12px;margin-bottom:6px;">'
                    f'<div style="font-size:10px;color:#787b86;">{exp}</div>'
                    f'<div style="font-size:18px;font-weight:500;color:{color};'
                    f'font-family:\'JetBrains Mono\',monospace;">{latest_iv:.2f}%</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    # ══════════════════════════════════
    # CHART
    # ══════════════════════════════════
    with chart_col:
        r = _SS.iv_result

        if r is None:
            st.markdown("""
            <div style="height:420px;display:flex;align-items:center;justify-content:center;
                        background:#1e222d;border:1px solid #2a2e39;border-radius:8px;">
              <div style="text-align:center;">
                <div style="font-size:32px;margin-bottom:12px;">🌡️</div>
                <div style="font-size:14px;color:#787b86;">Configure parameters and click Calculate IV</div>
              </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            fig = go.Figure()

            for i, exp in enumerate(r["expiries"]):
                df = r["series"][exp]
                color = EXPIRY_COLORS[i % len(EXPIRY_COLORS)]
                dash  = EXPIRY_DASH[i % len(EXPIRY_DASH)]
                latest = df["iv_pct"].iloc[-1]

                fig.add_trace(go.Scatter(
                    x=df["time"], y=df["iv_pct"],
                    mode="lines",
                    name=f"{exp}  {latest:.2f}%",
                    line=dict(color=color, width=1.8, dash=dash),
                    hovertemplate=f"<b>{exp}</b><br>IV: %{{y:.2f}}%<extra></extra>",
                ))

                # Annotation at last point
                fig.add_annotation(
                    x=df["time"].iloc[-1], y=latest,
                    text=f" {latest:.2f}%", showarrow=False,
                    font=dict(size=10, color="#fff", family="JetBrains Mono"),
                    bgcolor=color, borderpad=3, xanchor="left",
                )

            # Horizontal band: typical IV zone 10–25%
            fig.add_hrect(y0=10, y1=25, fillcolor="#2962ff", opacity=0.04,
                          line_width=0, annotation_text="Normal IV zone",
                          annotation_font=dict(size=9, color="#787b86"),
                          annotation_position="bottom right")

            idx_str = r["index"]
            title = (f"{idx_str} {r['strike']} {r['cp']} — Implied Volatility  [{r['tf']}]")

            fig.update_layout(
                title=dict(text=title, font=dict(size=12, color="#d1d4dc", family="IBM Plex Sans"), x=0),
                paper_bgcolor="#131722", plot_bgcolor="#131722",
                xaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                           tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                           showline=False, zeroline=False),
                yaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                           tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                           showline=False, zeroline=False, side="right",
                           title=dict(text="IV %", font=dict(size=11, color="#787b86")),
                           ticksuffix="%"),
                legend=dict(
                    font=dict(size=11, color="#d1d4dc"),
                    bgcolor="#1e222d", bordercolor="#2a2e39", borderwidth=1,
                    x=0.01, y=0.99, xanchor="left", yanchor="top",
                ),
                margin=dict(l=10, r=72, t=40, b=28), height=420,
                hovermode="x unified",
                hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                                font=dict(size=11, color="#d1d4dc", family="JetBrains Mono")),
            )

            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": True, "displaylogo": False,
                                    "toImageButtonOptions": {"format":"png","filename":"iv_chart"}})

            # ── Stats row ─────────────────────────────────────
            st.markdown('<div class="sec-header" style="margin-top:12px;">IV Summary</div>',
                        unsafe_allow_html=True)
            cols = st.columns(len(r["expiries"]))
            for col, (exp, color) in zip(cols, zip(r["expiries"],
                                                     [EXPIRY_COLORS[i] for i in range(len(r["expiries"]))])):
                df = r["series"][exp]
                iv_vals = df["iv_pct"]
                with col:
                    st.markdown(
                        f'<div class="stat-chip" style="border-left:3px solid {color};">'
                        f'<div class="sc-label">{exp}</div>'
                        f'<div class="sc-val" style="color:{color};">{iv_vals.iloc[-1]:.2f}%</div>'
                        f'<div style="font-size:10px;color:#787b86;margin-top:4px;font-family:\'JetBrains Mono\',monospace;">'
                        f'H: {iv_vals.max():.2f}% &nbsp; L: {iv_vals.min():.2f}%'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
