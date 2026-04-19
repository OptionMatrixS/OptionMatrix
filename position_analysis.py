import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import io

_SS = st.session_state

DISPLAY_COLS = [
    "ID", "Underlying", "Expiry Date", "Strike Price",
    "Scrip Type", "Net Position CF", "Price CF",
    "MTM", "Net Position", "BEP", "LTP",
    "IV", "Delta", "Vega", "Gamma", "Theta",
]
NUMERIC_COLS = [
    "Net Position CF", "Price CF", "MTM", "Net Position",
    "IV", "Delta", "Vega", "Gamma", "Theta",
]
COL_RENAME = {
    "ID": "ID", "Underlying": "Underlying", "Expiry Date": "Expiry",
    "Strike Price": "Strike", "Scrip Type": "Type",
    "Net Position CF": "Net Pos CF", "Price CF": "Price CF",
    "MTM": "MTM", "Net Position": "Net Pos", "BEP": "BEP", "LTP": "LTP",
    "IV": "IV %", "Delta": "Delta", "Vega": "Vega", "Gamma": "Gamma", "Theta": "Theta",
}

# ✅ FINAL FIXED FILE READER
def _read_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    raw  = uploaded.read()

    if name.endswith(".csv"):

        # Try multiple encodings first
        for enc in ("utf-8", "cp1252", "latin-1", "iso-8859-1", "utf-8-sig"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except Exception:
                continue

        # 🔥 FINAL SAFE PARSER (handles ALL bad CSVs)
        try:
            return pd.read_csv(
                io.BytesIO(raw),
                encoding="latin-1",
                on_bad_lines="skip",
                engine="python"
            )
        except TypeError:
            # Older pandas fallback
            return pd.read_csv(
                io.BytesIO(raw),
                encoding="latin-1",
                engine="python"
            )

    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))

    raise ValueError(f"Unsupported file type: {uploaded.name}")


def _clean_numeric(df):
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = (df[col].astype(str)
                       .str.replace(",", "", regex=False)
                       .str.replace(" ", "", regex=False))
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _init():
    for k, v in [
        ("pos_df", None),
        ("pos_checked", set()),
    ]:
        if k not in _SS:
            _SS[k] = v


def render():
    _init()

    st.markdown("## 📂 Position Data Analysis")

    uploaded = st.file_uploader(
        "Upload position file (.xlsx, .xls or .csv)",
        type=["xlsx", "csv", "xls"],
        key="pos_upload"
    )

    if uploaded is not None:
        try:
            df_raw = _read_file(uploaded)
            df_raw = _clean_numeric(df_raw)
            df_raw["_row_id"] = range(len(df_raw))

            _SS.pos_df = df_raw
            _SS.pos_checked = set()

            st.success(f"✅ Loaded {len(df_raw)} rows × {len(df_raw.columns)} columns")

        except Exception as e:
            st.error(f"❌ Failed to load file: {e}")
            return

    elif _SS.pos_df is not None:
        df_raw = _SS.pos_df
        st.info("📋 Using previously uploaded file.")

    else:
        st.info("Upload a file to begin")
        return

    df = _SS.pos_df

    st.markdown("### Preview")
    st.dataframe(df.head(50), use_container_width=True)
