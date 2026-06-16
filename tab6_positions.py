"""
Tab 6 — Position Analysis
Upload broker position export, filter, analyze, send to other tabs.
"""

import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO


EXPECTED_COLS = [
    "ID", "Underlying", "Expiry Date", "Strike Price", "Scrip Type",
    "Net Position CF", "Price CF", "MTM", "Net Position", "BEP",
    "LTP", "IV", "Delta", "Vega", "Gamma", "Theta"
]

GREEK_COLS = ["IV", "Delta", "Vega", "Gamma", "Theta"]


def _normalize_strike(x) -> int:
    try:
        return int(float(str(x).replace(",", "").strip()))
    except Exception:
        return 0


def _load_file(uploaded) -> pd.DataFrame:
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            if uploaded.name.endswith(".csv"):
                return pd.read_csv(uploaded, encoding=enc)
            else:
                return pd.read_excel(uploaded)
        except Exception:
            continue
    return pd.DataFrame()


def _bep_sign(row) -> float:
    bep = abs(float(row.get("BEP", 0) or 0))
    net = float(row.get("Net Position", 0) or 0)
    net_cf = float(row.get("Net Position CF", 0) or 0)
    if net > 0:
        return bep
    elif net < 0:
        return -bep
    elif net_cf > 0:
        return bep
    else:
        return -bep


def render(fyers):
    st.header("📋 Position Analysis")

    uploaded = st.file_uploader("Upload Position File (.xlsx / .csv)", type=["xlsx", "csv"])
    if not uploaded:
        st.info("Upload your broker position export to begin.")
        return

    df = _load_file(uploaded)
    if df.empty:
        st.error("Could not parse file.")
        return

    # Normalize columns
    df.columns = [c.strip() for c in df.columns]
    if "Strike Price" in df.columns:
        df["Strike Price"] = df["Strike Price"].apply(_normalize_strike)

    # Fix BEP signs
    if "BEP" in df.columns:
        df["BEP"] = df.apply(_bep_sign, axis=1)

    # ── Filters ──────────────────────────────────
    with st.expander("🔽 Filters", expanded=True):
        fc1, fc2, fc3 = st.columns(3)
        ids_available = sorted(df["ID"].dropna().unique().tolist()) if "ID" in df.columns else []
        und_available = sorted(df["Underlying"].dropna().unique().tolist()) if "Underlying" in df.columns else []
        exp_available = sorted(df["Expiry Date"].dropna().unique().tolist()) if "Expiry Date" in df.columns else []
        str_available = sorted(df["Strike Price"].dropna().unique().tolist()) if "Strike Price" in df.columns else []

        sel_ids  = fc1.multiselect("ID",         ids_available)
        sel_und  = fc2.multiselect("Underlying", und_available)
        sel_ot   = fc3.multiselect("Option Type", ["CE", "PE"])

        fc4, fc5 = st.columns(2)
        sel_exp  = fc4.multiselect("Expiry Date",  exp_available)
        sel_str  = fc5.multiselect("Strike Price", str_available)

    filtered = df.copy()
    if sel_ids: filtered = filtered[filtered["ID"].isin(sel_ids)]
    if sel_und: filtered = filtered[filtered["Underlying"].isin(sel_und)]
    if sel_ot and "Scrip Type" in filtered.columns:
        filtered = filtered[filtered["Scrip Type"].isin(sel_ot)]
    if sel_exp: filtered = filtered[filtered["Expiry Date"].isin(sel_exp)]
    if sel_str: filtered = filtered[filtered["Strike Price"].isin(sel_str)]

    # Row selection
    show_greeks = st.checkbox("Show Greeks Columns")
    display_cols = [c for c in EXPECTED_COLS if c in filtered.columns]
    if not show_greeks:
        display_cols = [c for c in display_cols if c not in GREEK_COLS]

    # Checkbox for each row
    st.markdown("**Select Rows**")
    col_a, col_b = st.columns([1, 1])
    if col_a.button("Select All"):
        st.session_state["pos_selected"] = list(range(len(filtered)))
    if col_b.button("Clear Selection"):
        st.session_state["pos_selected"] = []

    selected_indices = st.session_state.get("pos_selected", [])

    # Display with selection checkboxes
    checks = []
    for i, (_, row) in enumerate(filtered.iterrows()):
        checked = i in selected_indices
        checks.append(checked)

    # Use dataframe with event — simpler: render as table with styled rows
    edited = st.data_editor(
        filtered[display_cols].reset_index(drop=True),
        use_container_width=True,
        hide_index=False,
        key="pos_editor",
    )

    # ── Totals ───────────────────────────────────
    st.markdown("**Totals**")
    num_cols = ["MTM", "Net Position", "Net Position CF", "Delta", "Vega", "Gamma", "Theta"]
    totals = {}
    for c in num_cols:
        if c in filtered.columns:
            totals[c] = filtered[c].sum()

    # BEP weighted average
    if "BEP" in filtered.columns and "Net Position" in filtered.columns:
        weights = filtered["Net Position"].abs()
        w_sum = weights.sum()
        if w_sum != 0:
            wbep = (filtered["BEP"] * weights).sum() / w_sum
            net_dir = filtered["Net Position"].sum()
            totals["BEP (Wtd)"] = wbep if net_dir >= 0 else -abs(wbep)

    tot_df = pd.DataFrame([totals])
    st.dataframe(tot_df, use_container_width=True)

    # ── Export ───────────────────────────────────
    col_e1, col_e2 = st.columns(2)
    buf = BytesIO()
    filtered[display_cols].to_excel(buf, index=False)
    col_e1.download_button("📥 Export Excel", buf.getvalue(),
                           file_name="positions.xlsx")
    col_e2.download_button("📥 Export CSV", filtered[display_cols].to_csv(index=False),
                           file_name="positions.csv")

    # ── Send to other tabs ────────────────────────
    st.markdown("**Send Selected to…**")
    max_rows_sel = min(6, len(filtered))
    n_to_send = st.number_input("Rows to send", 1, len(filtered), max_rows_sel)
    c1, c2 = st.columns(2)
    if c1.button("📊 Send to Spread Chart (max 6)"):
        send_df = filtered.head(min(n_to_send, 6))
        st.session_state["send_to_spread"] = send_df.to_dict("records")
        st.success(f"Sent {len(send_df)} legs to Spread Chart (Tab 1). Switch tabs to view.")
    if c2.button("🧩 Send to Strategy Builder (max 10)"):
        send_df = filtered.head(min(n_to_send, 10))
        st.session_state["send_to_strategy"] = send_df.to_dict("records")
        st.success(f"Sent {len(send_df)} legs to Strategy Builder (Tab 7). Switch tabs to view.")
