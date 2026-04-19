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


def _read_file(uploaded) -> pd.DataFrame:
    name = uploaded.name.lower()
    raw  = uploaded.read()

    if name.endswith(".csv"):
        for enc in ("utf-8", "cp1252", "latin-1", "iso-8859-1", "utf-8-sig"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except Exception:
                continue
        # ✅ FIXED LINE (no errors=)
        return pd.read_csv(io.BytesIO(raw), encoding="latin-1")

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

def _fmt(val, decimals=2):
    if pd.isna(val): return "—"
    try:
        v = float(val)
        if abs(v) >= 1_00_000: return f"{v/1_00_000:+.2f}L"
        return f"{v:+,.{decimals}f}"
    except Exception:
        return str(val)

def _color(val):
    try:
        v = float(str(val).replace(",", ""))
        if v > 0: return "#26a69a"
        if v < 0: return "#ef5350"
    except Exception:
        pass
    return "#d1d4dc"

def _init():
    for k, v in [
        ("pos_df", None), ("pos_groups", {}),
        ("pos_checked", set()), ("pos_group_checked", {}),
    ]:
        if k not in _SS: _SS[k] = v


def _row_to_leg(row) -> dict:
    underlying = str(row.get("Underlying", "NIFTY")).strip().upper()
    if underlying not in ("NIFTY", "SENSEX", "BANKNIFTY"):
        underlying = "NIFTY"
    try:
        expiry_dt    = pd.to_datetime(row.get("Expiry Date"))
        expiry_label = expiry_dt.strftime("%-d %b %y") + " (M)"
    except Exception:
        expiry_label = str(row.get("Expiry Date", ""))
    try:
        strike = int(float(str(row.get("Strike Price", 0)).replace(",", "")))
    except Exception:
        strike = 0
    cp = str(row.get("Scrip Type", "CE")).strip().upper()
    if cp not in ("CE", "PE"): cp = "CE"
    try:
        net_cf = float(str(row.get("Net Position CF", 0)).replace(",", ""))
    except Exception:
        net_cf = 0
    bs    = "Buy" if net_cf >= 0 else "Sell"
    ratio = max(1, min(10, abs(int(net_cf)) if net_cf != 0 else 1))
    try:
        ltp = float(str(row.get("LTP", 0)).replace(",", ""))
    except Exception:
        ltp = 0.0
    signed = ltp * ratio if bs == "Buy" else -ltp * ratio
    return dict(index=underlying, strike=strike, expiry=expiry_label,
                cp=cp, bs=bs, ratio=ratio, ltp=ltp, net=round(signed, 2))


def render():
    _init()

    st.markdown("## 📂 Position Data Analysis")

    uploaded = st.file_uploader(
        "Upload position file (.xlsx, .xls or .csv)",
        type=["xlsx", "csv", "xls"], key="pos_upload")

    if uploaded is not None:
        try:
            df_raw = _read_file(uploaded)
            df_raw = _clean_numeric(df_raw)
            df_raw["_row_id"] = range(len(df_raw))
            _SS.pos_df      = df_raw
            _SS.pos_checked = set()
            st.success(f"✅ Loaded {len(df_raw)} rows")
        except Exception as e:
            st.error(f"Failed to load file: {e}")
            return
    elif _SS.pos_df is not None:
        df_raw = _SS.pos_df
    else:
        st.info("Upload a file to begin")
        return

    df = _SS.pos_df
    st.dataframe(df.head(50))
