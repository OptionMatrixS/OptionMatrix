"""
Shared UI utilities: theme, stat chips, plotly layout, IST time.
"""

import plotly.graph_objects as go
import pandas as pd
import streamlit as st


# ─────────── THEME ────────────────────────────────────
BG       = "#131722"
PANEL    = "#1e222d"
BORDER   = "#2a2e39"
TEXT     = "#d1d4dc"
MUTED    = "#787b86"
GREEN    = "#26a69a"
RED      = "#ef5350"
BLUE     = "#2962ff"
ORANGE   = "#ff9800"
PURPLE   = "#9c27b0"
ROW_BASE = "#162040"


def now_ist() -> pd.Timestamp:
    """Current IST time without timezone info (Streamlit Cloud safe)."""
    return pd.Timestamp.now(tz="Asia/Kolkata").replace(tzinfo=None)


def dark_layout(title: str = "", height: int = 420) -> dict:
    return dict(
        paper_bgcolor=BG,
        plot_bgcolor=PANEL,
        font=dict(color=TEXT, size=12),
        title=dict(text=title, font=dict(color=TEXT, size=14)) if title else None,
        height=height,
        margin=dict(l=50, r=20, t=40 if title else 20, b=40),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT)),
    )


def apply_dark_css():
    st.markdown(f"""
    <style>
    /* Root dark theme */
    .stApp {{ background-color: {BG}; color: {TEXT}; }}
    .stSidebar {{ background-color: {PANEL}; }}
    .stTabs [data-baseweb="tab-list"] {{ background-color: {PANEL}; border-bottom: 1px solid {BORDER}; }}
    .stTabs [data-baseweb="tab"] {{ color: {MUTED}; }}
    .stTabs [aria-selected="true"] {{ color: {TEXT}; border-bottom: 2px solid {BLUE}; }}
    div[data-testid="metric-container"] {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 8px 14px; }}
    .stDataFrame {{ background: {PANEL}; }}
    .chip-label {{ font-size: 11px; color: {MUTED}; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 2px; }}
    .chip-value {{ font-size: 22px; font-weight: 700; }}
    .chip-green {{ color: {GREEN}; }}
    .chip-red   {{ color: {RED};   }}
    .chip-blue  {{ color: {BLUE};  }}
    .chip-orange{{ color: {ORANGE};}}
    .chip-text  {{ color: {TEXT};  }}
    .chip-box   {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; padding: 10px 16px; margin: 4px 0; }}
    .market-closed-banner {{
        background: #2a1f00; border: 1px solid {ORANGE}; border-radius: 6px;
        padding: 8px 16px; color: {ORANGE}; font-size: 13px; margin-bottom: 12px;
    }}
    </style>
    """, unsafe_allow_html=True)


def stat_chip(label: str, value, color: str = "text"):
    """Render a single stat chip."""
    cls = f"chip-{color}"
    st.markdown(f"""
    <div class="chip-box">
      <div class="chip-label">{label}</div>
      <div class="chip-value {cls}">{value}</div>
    </div>
    """, unsafe_allow_html=True)


def stat_chips_row(chips: list[tuple]):
    """
    Render a row of stat chips.
    chips = list of (label, value, color)
    """
    cols = st.columns(len(chips))
    for col, (label, value, color) in zip(cols, chips):
        with col:
            stat_chip(label, value, color)


def market_closed_notice():
    st.markdown("""
    <div class="market-closed-banner">
    🔴 Market Closed — Showing Previous Close Prices
    </div>
    """, unsafe_allow_html=True)


def fmt_price(v: float) -> str:
    if v >= 1000:
        return f"₹{v:,.2f}"
    return f"₹{v:.2f}"


def fmt_pnl(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}₹{v:,.0f}"
