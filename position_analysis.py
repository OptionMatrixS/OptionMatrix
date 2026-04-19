import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import io

_SS = st.session_state

DISPLAY_COLS = [
    "ID", "Underlying", "Expiry Date", "Strike Price",
    "Scrip Type", "Net Position CF", "Price CF",
    "MTM", "Net Position", "BEP", "LTP",
]

NUMERIC_COLS = [
    "Net Position CF", "Price CF", "MTM", "Net Position", "BEP"
]

# ─────────────────────────────────────────────
# FILE READER (ROBUST)
# ─────────────────────────────────────────────
def _read_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    raw = uploaded.read()

    if name.endswith(".csv"):
        for enc in ("utf-8", "cp1252", "latin-1", "iso-8859-1", "utf-8-sig"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except Exception:
                continue

        try:
            return pd.read_csv(
                io.BytesIO(raw),
                encoding="latin-1",
                on_bad_lines="skip",
                engine="python"
            )
        except TypeError:
            return pd.read_csv(
                io.BytesIO(raw),
                encoding="latin-1",
                engine="python"
            )

    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))

    raise ValueError("Unsupported file type")


# ─────────────────────────────────────────────
def _clean_numeric(df):
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(",", "", regex=False)
                .str.replace(" ", "", regex=False)
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fmt(x):
    if pd.isna(x):
        return "—"
    return f"{x:+,.2f}"


def _color(x):
    if pd.isna(x):
        return "#d1d4dc"
    return "#26a69a" if x > 0 else "#ef5350" if x < 0 else "#d1d4dc"


# ─────────────────────────────────────────────
def render():
    st.title("📊 Position Analysis")

    uploaded = st.file_uploader("Upload CSV / Excel", type=["csv", "xlsx", "xls"])

    if uploaded is None:
        st.info("Upload file to begin")
        return

    df = _read_file(uploaded)
    df = _clean_numeric(df)

    # Debug (optional)
    st.write("Detected Columns:", df.columns.tolist())

    # ─────────────────────────────────────────
    # FILTERS
    # ─────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        if "ID" in df.columns:
            ids = df["ID"].dropna().unique().tolist()
            sel_id = st.multiselect("ID", ids, default=ids[:1])
            df = df[df["ID"].isin(sel_id)]

    with col2:
        if "Underlying" in df.columns:
            und = df["Underlying"].dropna().unique().tolist()
            sel_und = st.multiselect("Underlying", und, default=und)
            df = df[df["Underlying"].isin(sel_und)]

    with col3:
        if "Strike Price" in df.columns:
            strikes = sorted(df["Strike Price"].dropna().unique())
            sel_strike = st.multiselect("Strike Price", strikes, default=strikes)
            df = df[df["Strike Price"].isin(sel_strike)]

    if df.empty:
        st.warning("No data after filters")
        return

    # ─────────────────────────────────────────
    # BEP SIGN LOGIC
    # ─────────────────────────────────────────
    def fix_bep(row):
        bep = row.get("BEP", 0)
        net_pos = row.get("Net Position", 0)
        net_cf = row.get("Net Position CF", 0)

        if pd.isna(bep):
            return 0

        if net_pos != 0:
            return abs(bep) if net_pos > 0 else -abs(bep)
        else:
            return abs(bep) if net_cf > 0 else -abs(bep)

    if "BEP" in df.columns:
        df["BEP"] = df.apply(fix_bep, axis=1)

    # ─────────────────────────────────────────
    # SAFE COLUMN SELECTION
    # ─────────────────────────────────────────
    available_cols = [c for c in DISPLAY_COLS if c in df.columns]

    # ─────────────────────────────────────────
    # DISPLAY TABLE
    # ─────────────────────────────────────────
    st.subheader("📋 Data")
    st.dataframe(df[available_cols], use_container_width=True)

    # ─────────────────────────────────────────
    # TOTALS
    # ─────────────────────────────────────────
    st.subheader("📊 Totals")

    totals = {}
    for col in available_cols:
        if col in NUMERIC_COLS:
            totals[col] = df[col].sum()
        else:
            totals[col] = "TOTAL"

    st.dataframe(pd.DataFrame([totals]), use_container_width=True)
