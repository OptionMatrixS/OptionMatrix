"""Global design system for Option Matrix — Bloomberg/TradingView dark.

Every colour and reusable HTML pattern lives here so the look stays identical
across all tabs. Import PALETTE / LEG_COLORS and the helper functions; never
hand-write a hex code in a tab file.
"""

# --- Colour palette (single source of truth) -------------------------------
PALETTE = {
    "BG":     "#131722",  # page background
    "PANEL":  "#1e222d",  # card / panel background
    "BORDER": "#2a2e39",  # borders / gridlines
    "TEXT":   "#d1d4dc",  # primary text
    "MUTED":  "#787b86",  # muted text
    "GREEN":  "#26a69a",  # profit / buy
    "RED":    "#ef5350",  # loss / sell
    "BLUE":   "#2962ff",  # accent
    "ORANGE": "#ff9800",  # warning
    "PURPLE": "#9c27b0",  # vega
    "CYAN":   "#00bcd4",  # leg 6 / misc
}

# Per-leg badge colour, 1-indexed in the UI (leg 1 -> index 0).
LEG_COLORS = [
    PALETTE["BLUE"],    # Leg 1
    PALETTE["GREEN"],   # Leg 2
    PALETTE["ORANGE"],  # Leg 3
    PALETTE["RED"],     # Leg 4
    PALETTE["PURPLE"],  # Leg 5
    PALETTE["CYAN"],    # Leg 6
]


def leg_color(n: int) -> str:
    """Colour for leg number n (1-indexed). Wraps if more than 6."""
    if n < 1:
        n = 1
    return LEG_COLORS[(n - 1) % len(LEG_COLORS)]


# --- CSS injected once at app start ----------------------------------------
def inject_css() -> None:
    import streamlit as st

    p = PALETTE
    css = f"""
    <style>
      .stApp {{ background:{p['BG']}; color:{p['TEXT']}; }}
      section[data-testid="stSidebar"] {{ background:{p['PANEL']};
          border-right:1px solid {p['BORDER']}; }}
      section[data-testid="stSidebar"] * {{ color:{p['TEXT']}; }}
      h1,h2,h3,h4,h5,h6 {{ color:{p['TEXT']}; }}
      .block-container {{ padding-top:1.2rem; padding-bottom:2rem; }}
      /* Buttons */
      .stButton>button {{
          background:{p['PANEL']}; color:{p['TEXT']};
          border:1px solid {p['BORDER']}; border-radius:6px;
          padding:6px 12px; font-weight:600; transition:.15s;
      }}
      .stButton>button:hover {{ border-color:{p['BLUE']}; color:#fff; }}
      /* Inputs */
      .stTextInput input, .stNumberInput input, .stDateInput input,
      div[data-baseweb="select"]>div {{
          background:{p['BG']}; color:{p['TEXT']};
          border:1px solid {p['BORDER']}; border-radius:6px;
      }}
      label, .stMarkdown {{ color:{p['TEXT']}; }}
      /* Tabs */
      .stTabs [data-baseweb="tab-list"] {{ gap:4px; border-bottom:1px solid {p['BORDER']}; }}
      .stTabs [data-baseweb="tab"] {{
          background:{p['PANEL']}; color:{p['MUTED']};
          border:1px solid {p['BORDER']}; border-bottom:none;
          border-radius:6px 6px 0 0; padding:6px 14px;
      }}
      .stTabs [aria-selected="true"] {{ color:#fff; border-color:{p['BLUE']}; }}
      /* DataFrame */
      .stDataFrame {{ border:1px solid {p['BORDER']}; border-radius:6px; }}
      /* Metric */
      div[data-testid="stMetricValue"] {{ color:{p['TEXT']}; }}
      hr {{ border-color:{p['BORDER']}; }}
      #MainMenu, footer {{ visibility:hidden; }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# --- Reusable HTML fragments -----------------------------------------------
def chip(label: str, value, color: str = None) -> str:
    """A stat chip. Returns an HTML string; render with st.markdown(..., True)."""
    c = color or PALETTE["GREEN"]
    return (
        f'<div style="background:{PALETTE["PANEL"]};border:1px solid '
        f'{PALETTE["BORDER"]};border-radius:6px;padding:10px 14px;">'
        f'<div style="font-size:10px;color:{PALETTE["MUTED"]};'
        f'text-transform:uppercase;letter-spacing:.06em;">{label}</div>'
        f'<div style="font-size:18px;font-weight:600;color:{c};">{value}</div>'
        f'</div>'
    )


def chips_row(items) -> str:
    """items = list of (label, value[, color]). Returns a flex row of chips."""
    cells = []
    for it in items:
        lbl, val = it[0], it[1]
        col = it[2] if len(it) > 2 else None
        cells.append(chip(lbl, val, col))
    inner = "".join(f'<div style="flex:1;min-width:120px;">{c}</div>' for c in cells)
    return f'<div style="display:flex;gap:8px;flex-wrap:wrap;">{inner}</div>'


def section(title: str) -> str:
    return (
        f'<div style="font-size:11px;color:{PALETTE["MUTED"]};'
        f'text-transform:uppercase;letter-spacing:.08em;'
        f'border-bottom:1px solid {PALETTE["BORDER"]};'
        f'padding-bottom:4px;margin:12px 0 8px;">{title}</div>'
    )


def leg_header(n: int) -> str:
    c = leg_color(n)
    return (
        f'<div style="display:inline-block;background:{c};color:#fff;'
        f'font-size:11px;font-weight:700;border-radius:4px;'
        f'padding:2px 8px;margin-bottom:4px;">LEG {n}</div>'
    )


# --- Plotly base layout -----------------------------------------------------
def plotly_layout(title: str = "", height: int = 420) -> dict:
    """Base layout dict for every chart so styling stays uniform."""
    p = PALETTE
    return dict(
        title=dict(text=title, font=dict(color=p["TEXT"], size=14)),
        paper_bgcolor=p["BG"],
        plot_bgcolor=p["BG"],
        height=height,
        margin=dict(l=10, r=10, t=40 if title else 14, b=10),
        font=dict(color=p["MUTED"], size=11),
        legend=dict(font=dict(color=p["MUTED"], size=10),
                    bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor=p["PANEL"], zerolinecolor=p["BORDER"],
                   tickfont=dict(color=p["MUTED"]), linecolor=p["BORDER"]),
        yaxis=dict(gridcolor=p["PANEL"], zerolinecolor=p["BORDER"],
                   tickfont=dict(color=p["MUTED"]), linecolor=p["BORDER"],
                   side="right"),
        hovermode="x unified",
    )
