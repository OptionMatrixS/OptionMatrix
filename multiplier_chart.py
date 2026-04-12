"""pages/multiplier_chart.py
SENSEX-NIFTY Synthetic Multiplier
Replicates the TradingView Pine Script:
  sx_synth = SX_strike + sx_CE - sx_PE
  n_synth  = N_strike  + n_CE  - n_PE
  multiplier = sx_synth / n_synth
"""

import streamlit as st
import plotly.graph_objects as go
from data_helpers import (
    NIFTY_STRIKES, SENSEX_STRIKES, NIFTY_EXPIRIES, SENSEX_EXPIRIES,
    get_multiplier_series, TF_MAP
)

_SS = st.session_state


def _init():
    defaults = {
        "mx_sx_strike": 84000, "mx_sx_exp": "11 Apr",
        "mx_n_strike":  22800, "mx_n_exp":  "13 Apr",
        "mx_tf": "1m", "mx_result": None,
    }
    for k, v in defaults.items():
        if k not in _SS:
            _SS[k] = v


def render():
    _init()

    st.markdown("""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
      <div style="font-size:20px;font-weight:600;color:#d1d4dc;">✖️ Multiplier Chart</div>
      <div style="font-size:11px;color:#787b86;padding:3px 10px;background:#1e222d;
                  border:1px solid #2a2e39;border-radius:10px;">SENSEX / NIFTY Synthetic</div>
    </div>
    <div style="font-size:12px;color:#787b86;margin-bottom:16px;">
      Tracks the synthetic ratio: <code style="color:#2962ff;background:#1e222d;padding:1px 5px;border-radius:3px;">
      (SX_strike + SX_CE − SX_PE) ÷ (N_strike + N_CE − N_PE)</code>
    </div>
    """, unsafe_allow_html=True)

    ctrl_col, chart_col = st.columns([1, 2.5], gap="medium")

    # ══════════════════════════════════
    # CONTROLS
    # ══════════════════════════════════
    with ctrl_col:
        st.markdown("""
        <div style="background:#1e222d;border:1px solid #2a2e39;border-left:3px solid #4caf50;
                    border-radius:6px;padding:10px 14px;margin-bottom:14px;">
          <div style="font-size:11px;font-weight:500;color:#4caf50;margin-bottom:6px;">SENSEX (BSE)</div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        sx_s_idx = SENSEX_STRIKES.index(
            min(SENSEX_STRIKES, key=lambda x: abs(x - 84000))
        )
        sx_strike = st.selectbox("SENSEX Strike", SENSEX_STRIKES,
                                  index=sx_s_idx, key="mx_sx_str")
        sx_exp = st.selectbox("SENSEX Expiry", SENSEX_EXPIRIES,
                               index=0, key="mx_sx_exp_sel")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="background:#1e222d;border:1px solid #2a2e39;border-left:3px solid #9c27b0;
                    border-radius:6px;padding:10px 14px;margin-bottom:14px;">
          <div style="font-size:11px;font-weight:500;color:#9c27b0;margin-bottom:6px;">NIFTY (NSE)</div>
        </div>
        """, unsafe_allow_html=True)

        n_s_idx = NIFTY_STRIKES.index(
            min(NIFTY_STRIKES, key=lambda x: abs(x - 22800))
        )
        n_strike = st.selectbox("NIFTY Strike", NIFTY_STRIKES,
                                 index=n_s_idx, key="mx_n_str")
        n_exp = st.selectbox("NIFTY Expiry", NIFTY_EXPIRIES,
                              index=1, key="mx_n_exp_sel")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        tf = st.selectbox("Timeframe", list(TF_MAP.keys()), key="mx_tf_sel")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("📡  Plot Multiplier", use_container_width=True, type="primary"):
            df = get_multiplier_series(sx_strike, sx_exp, n_strike, n_exp,
                                        n_bars=80, tf_minutes=TF_MAP[tf])
            _SS.mx_result = dict(
                df=df, sx_strike=sx_strike, sx_exp=sx_exp,
                n_strike=n_strike, n_exp=n_exp, tf=tf,
            )
            st.rerun()

        # ── Stats panel ───────────────────────────────────────
        if _SS.mx_result:
            r = _SS.mx_result
            df = r["df"]
            last_mult = df["multiplier"].iloc[-1]
            avg_mult  = df["multiplier"].mean()
            hi_mult   = df["multiplier"].max()
            lo_mult   = df["multiplier"].min()
            chg       = last_mult - df["multiplier"].iloc[0]

            st.markdown("---")
            st.markdown('<div class="sec-header">Live Stats</div>', unsafe_allow_html=True)

            for label, val, color in [
                ("Multiplier", f"{last_mult:.4f}", "#26a69a" if chg >= 0 else "#ef5350"),
                ("Change",     f"{chg:+.4f}",      "#26a69a" if chg >= 0 else "#ef5350"),
                ("Average",    f"{avg_mult:.4f}",   "#d1d4dc"),
                ("High",       f"{hi_mult:.4f}",    "#26a69a"),
                ("Low",        f"{lo_mult:.4f}",    "#ef5350"),
            ]:
                st.markdown(
                    f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:5px;'
                    f'padding:8px 12px;margin-bottom:5px;display:flex;justify-content:space-between;">'
                    f'<span style="font-size:11px;color:#787b86;">{label}</span>'
                    f'<span style="font-size:12px;font-weight:500;color:{color};'
                    f'font-family:\'JetBrains Mono\',monospace;">{val}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

    # ══════════════════════════════════
    # CHART
    # ══════════════════════════════════
    with chart_col:
        r = _SS.mx_result

        if r is None:
            st.markdown("""
            <div style="height:480px;display:flex;align-items:center;justify-content:center;
                        background:#1e222d;border:1px solid #2a2e39;border-radius:8px;">
              <div style="text-align:center;">
                <div style="font-size:32px;margin-bottom:12px;">✖️</div>
                <div style="font-size:14px;color:#787b86;">Configure strikes &amp; expiries, then click Plot Multiplier</div>
              </div>
            </div>
            """, unsafe_allow_html=True)
            return

        df = r["df"]
        last  = df["multiplier"].iloc[-1]
        first = df["multiplier"].iloc[0]
        line_color = "#26a69a" if last >= first else "#ef5350"

        fig = go.Figure()

        # Average line
        avg = df["multiplier"].mean()
        fig.add_hline(y=avg, line=dict(color="#787b86", width=1, dash="dash"),
                      annotation_text=f"Avg {avg:.4f}",
                      annotation_font=dict(size=10, color="#787b86"),
                      annotation_position="right")

        # Main multiplier line
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["multiplier"],
            mode="lines", name="Multiplier",
            line=dict(color=line_color, width=2),
            fill="tozeroy",
            fillcolor=f"rgba({'38,166,154' if line_color=='#26a69a' else '239,83,80'},0.07)",
            hovertemplate="<b>Multiplier</b>: %{y:.4f}<extra></extra>",
        ))

        # Last value annotation
        fig.add_annotation(
            x=df["time"].iloc[-1], y=last,
            text=f" {last:.4f}", showarrow=False,
            font=dict(size=11, color="#fff", family="JetBrains Mono"),
            bgcolor=line_color, borderpad=4, xanchor="left",
        )

        title = (f"SENSEX {r['sx_strike']} ({r['sx_exp']})  /  "
                 f"NIFTY {r['n_strike']} ({r['n_exp']})  —  Multiplier  [{r['tf']}]")

        fig.update_layout(
            title=dict(text=title, font=dict(size=12, color="#d1d4dc", family="IBM Plex Sans"), x=0),
            paper_bgcolor="#131722", plot_bgcolor="#131722",
            xaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                       tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                       rangeslider=dict(visible=False), showline=False, zeroline=False),
            yaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                       tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                       showline=False, zeroline=False, side="right",
                       title=dict(text="Multiplier", font=dict(size=11, color="#787b86"))),
            legend=dict(font=dict(size=11, color="#787b86"), bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=10, r=80, t=40, b=28), height=400,
            hovermode="x unified",
            hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                            font=dict(size=11, color="#d1d4dc", family="JetBrains Mono")),
        )
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": True, "displaylogo": False,
                                "toImageButtonOptions": {"format":"png","filename":"multiplier_chart"}})

        # ── Synthetic spot sub-chart ───────────────────────
        st.markdown('<div class="sec-header" style="margin-top:8px;">Synthetic Spot Comparison</div>',
                    unsafe_allow_html=True)

        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=df["time"], y=df["sx_synth"], mode="lines",
            name="SENSEX Synthetic",
            line=dict(color="#4caf50", width=1.5),
            yaxis="y1",
        ))
        fig2.add_trace(go.Scatter(
            x=df["time"], y=df["n_synth"], mode="lines",
            name="NIFTY Synthetic",
            line=dict(color="#9c27b0", width=1.5, dash="dash"),
            yaxis="y2",
        ))
        fig2.update_layout(
            paper_bgcolor="#131722", plot_bgcolor="#131722",
            xaxis=dict(gridcolor="#1e222d", gridwidth=0.5,
                       tickfont=dict(size=10, color="#787b86", family="JetBrains Mono"),
                       showline=False, zeroline=False),
            yaxis=dict(gridcolor="#1e222d", side="left",
                       tickfont=dict(size=9, color="#4caf50", family="JetBrains Mono"),
                       showline=False, zeroline=False,
                       title=dict(text="SENSEX Synthetic", font=dict(size=10, color="#4caf50"))),
            yaxis2=dict(overlaying="y", side="right",
                        tickfont=dict(size=9, color="#9c27b0", family="JetBrains Mono"),
                        showline=False, zeroline=False,
                        title=dict(text="NIFTY Synthetic", font=dict(size=10, color="#9c27b0"))),
            legend=dict(font=dict(size=11, color="#d1d4dc"), bgcolor="#1e222d",
                        bordercolor="#2a2e39", borderwidth=1, x=0.01, y=0.99),
            margin=dict(l=10, r=80, t=10, b=28), height=200,
            hovermode="x unified",
            hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                            font=dict(size=11, color="#d1d4dc", family="JetBrains Mono")),
        )
        st.plotly_chart(fig2, use_container_width=True,
                        config={"displayModeBar": False, "displaylogo": False})
