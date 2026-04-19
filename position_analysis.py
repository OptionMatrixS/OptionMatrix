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

# ✅ ROBUST CSV READER (FIXED)
def _read_file(uploaded):
    import io
    name = uploaded.name.lower()
    raw = uploaded.read()

    if name.endswith(".csv"):
        for enc in ["utf-8", "cp1252", "latin-1", "iso-8859-1"]:
            try:
                return pd.read_csv(
                    io.TextIOWrapper(io.BytesIO(raw), encoding=enc),
                    engine="python",
                    on_bad_lines="skip"
                )
            except Exception:
                continue

        return pd.read_csv(
            io.TextIOWrapper(io.BytesIO(raw), encoding="latin-1"),
            engine="python",
            on_bad_lines="skip"
        )
    else:
        return pd.read_excel(io.BytesIO(raw))

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
    except:
        return str(val)

def _color(val):
    try:
        v = float(str(val).replace(",", ""))
        if v > 0: return "#26a69a"
        if v < 0: return "#ef5350"
    except:
        pass
    return "#d1d4dc"

def _init():
    for k, v in [("pos_df", None), ("pos_checked", set())]:
        if k not in _SS: _SS[k] = v

# ─────────────────────────────────────────────
def render():
    _init()

    st.markdown("## 📂 Position Data Analysis")

    uploaded = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"])

    if uploaded is not None:
        try:
            df_raw = _read_file(uploaded)
            df_raw = _clean_numeric(df_raw)
            df_raw["_row_id"] = range(len(df_raw))
            _SS.pos_df = df_raw
            _SS.pos_checked = set()
            st.success(f"✅ Loaded {len(df_raw)} rows")
        except Exception as e:
            st.error(f"Failed to load file: {e}")
            return
    elif _SS.pos_df is not None:
        df_raw = _SS.pos_df
    else:
        st.info("Upload file to begin")
        return

    df = df_raw.copy()

    # ── FILTERS ──
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

    # ── BEP SIGN LOGIC ──
    def fix_bep(row):
        try:
            bep = float(row.get("BEP", 0))
            net_pos = float(row.get("Net Position", 0))
            net_cf  = float(row.get("Net Position CF", 0))

            if net_pos != 0:
                return abs(bep) if net_pos > 0 else -abs(bep)
            else:
                return abs(bep) if net_cf > 0 else -abs(bep)
        except:
            return 0

    if "BEP" in df.columns:
        df["BEP"] = df.apply(fix_bep, axis=1)

    # ── SAFE COLUMN DISPLAY ──
    available_cols = [c for c in DISPLAY_COLS if c in df.columns]

    st.subheader("📋 Data")
    st.dataframe(df[available_cols], use_container_width=True)

    # ── TOTALS ──
    st.subheader("📊 Totals")

    totals = {}

    for col in available_cols:
        if col in NUMERIC_COLS:
            totals[col] = df[col].sum()
        elif col == "BEP":
            signed_bep = []
            for _, r in df.iterrows():
                try:
                    bep = float(r.get("BEP", 0))
                    npv = float(r.get("Net Position", 0))
                    ncf = float(r.get("Net Position CF", 0))

                    if npv != 0:
                        bep = abs(bep) if npv > 0 else -abs(bep)
                    else:
                        bep = abs(bep) if ncf > 0 else -abs(bep)

                    signed_bep.append(bep)
                except:
                    pass

            totals[col] = sum(signed_bep)
        else:
            totals[col] = "TOTAL"

    st.dataframe(pd.DataFrame([totals]), use_container_width=True)
