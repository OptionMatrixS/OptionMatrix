"""
live_bhavcopy.py  —  Live Bhavcopy Tab
Shows all strikes with volume today for selected index/stock and expiry.
"""
import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd
import io
from fyers_client import get_fyers_client, get_expiries, _s
from fyers_apiv3 import fyersModel

_SS = st.session_state

# All F&O stocks available on NSE
_FNO_STOCKS = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","KOTAKBANK",
    "SBIN","BAJFINANCE","BHARTIARTL","ITC","AXISBANK","LT","ASIANPAINT",
    "MARUTI","TITAN","SUNPHARMA","ULTRACEMCO","WIPRO","HCLTECH","TECHM",
    "INDUSINDBK","BAJAJFINSV","NESTLEIND","POWERGRID","NTPC","ONGC",
    "COALINDIA","TATAMOTORS","TATASTEEL","JSWSTEEL","HINDALCO","VEDL",
    "GRASIM","ADANIENT","ADANIPORTS","DIVISLAB","DRREDDY","CIPLA","APOLLOHOSP",
    "EICHERMOT","HEROMOTOCO","BAJAJ-AUTO","M&M","TATACONSUM","BRITANNIA",
    "PIDILITIND","HAVELLS","MUTHOOTFIN","PAGEIND","VOLTAS","BERGEPAINT",
    "LUPIN","BIOCON","AUROPHARMA","IPCALAB","TORNTPHARM","ALKEM","GLAXO",
    "NAUKRI","JUSTDIAL","IRCTC","DMART","ZOMATO","PAYTM","POLICYBZR",
    "BANDHANBNK","FEDERALBNK","IDFCFIRSTB","PNB","BANKBARODA","CANBK",
    "GMRINFRA","CONCOR","BALKRISIND","ABBOTINDIA","CHOLAFIN","MANAPPURAM",
    "LICHSGFIN","SBILIFE","HDFCLIFE","ICICIPRULI","GICRE","NIACL",
    "COFORGE","MPHASIS","PERSISTENT","LTIM","OFSS","KPITTECH",
    "INDIGO","SPICEJET","SAIL","NMDC","MOIL","NATIONALUM",
    "DEEPAKNTR","AARTIIND","PIIND","UPL","BPCL","IOC","HINDPETRO",
    "GAIL","PETRONET","IGL","MGL","ATGL",
]
_FNO_STOCKS = sorted(set(_FNO_STOCKS))

_OPTIDX_MAP = {
    "NIFTY":     "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "SENSEX":    "BSE:SENSEX-INDEX",
    "FINNIFTY":  "NSE:FINNIFTY-INDEX",
}

def _get_option_chain(symbol_key: str, expiry_code: str = "") -> pd.DataFrame:
    """Fetch full option chain for a symbol from Fyers."""
    try:
        fyers = get_fyers_client()
        resp  = fyers.optionchain(data={
            "symbol": symbol_key, "strikecount": 0, "timestamp": expiry_code or ""})
        if not (resp and resp.get("s") == "ok"):
            return pd.DataFrame()
        chain = resp.get("data", {}).get("optionsChain", [])
        if not chain:
            return pd.DataFrame()
        rows = []
        for opt in chain:
            if not isinstance(opt, dict): continue
            rows.append({
                "Strike Price": opt.get("strikePrice", 0),
                "Option Type":  opt.get("option_type", ""),
                "Volume":       opt.get("volume", 0),
                "OI":           opt.get("oi", 0),
                "LTP":          opt.get("ltp", 0),
                "Expiry":       opt.get("expiry", ""),
            })
        return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"Option chain fetch failed: {e}")
        return pd.DataFrame()


def render():
    st.markdown(
        '<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">'
        '📋 Live Bhavcopy</div>', unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:12px;color:#787b86;margin-bottom:16px;">'
        'All strikes with volume today — live from Fyers option chain.</div>',
        unsafe_allow_html=True)

    # ── Instrument type ────────────────────────────────────────────────────────
    st.markdown('<div class="sec-header">Filters</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        inst_type = st.radio(
            "Instrument Type", ["OPTIDX (Index Options)", "OPTSTK (Stock Options)"],
            key="bh_inst_type", horizontal=True)

    with c2:
        if "OPTIDX" in inst_type:
            idx_sel = st.selectbox(
                "Select Index",
                ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"],
                key="bh_idx_sel")
            symbol_key  = _OPTIDX_MAP.get(idx_sel, "NSE:NIFTY50-INDEX")
            symbol_name = idx_sel
            exchange    = "BSE" if idx_sel == "SENSEX" else "NSE"
        else:
            all_opt  = ["— Select All —"] + _FNO_STOCKS
            stk_sel  = st.multiselect(
                "Select Stocks", all_opt,
                default=["— Select All —"], key="bh_stk_sel")
            if "— Select All —" in stk_sel:
                selected_stocks = _FNO_STOCKS
            else:
                selected_stocks = [s for s in stk_sel if s != "— Select All —"]
            symbol_key  = f"NSE:{selected_stocks[0]}-EQ" if selected_stocks else ""
            symbol_name = selected_stocks[0] if selected_stocks else ""
            exchange    = "NSE"

    # ── Expiry selector ────────────────────────────────────────────────────────
    c3, c4, c5, c6 = st.columns(4)
    with c3:
        try:
            if "OPTIDX" in inst_type:
                expiries = get_expiries(idx_sel if "OPTIDX" in inst_type else symbol_name)
            else:
                expiries = get_expiries("NIFTY")   # fallback for stocks
            exp_sel = st.selectbox("Expiry", expiries, key="bh_expiry")
        except Exception as e:
            st.error(f"Load expiries failed: {e}")
            return

    with c4:
        vol_gt = st.number_input(
            "Volume Greater Than", min_value=0, value=0, step=100,
            key="bh_vol_gt",
            help="Only show strikes where volume > this value")

    with c5:
        new_oi_only = st.checkbox(
            "New OI Data Only",
            value=False, key="bh_new_oi",
            help="Show only strikes where OI = 0 (new positions built today)")

    with c6:
        opt_type_filter = st.selectbox(
            "Option Type", ["Both", "CE Only", "PE Only"], key="bh_opt_type")

    fetch_btn = st.button("📡  Fetch Bhavcopy", type="primary",
                           use_container_width=False, key="bh_fetch")

    if fetch_btn:
        with st.spinner("Fetching live option chain data…"):
            # Get expiry code from label
            exp_codes = _SS.get(f"expiries_{'NIFTY' if 'OPTSTK' in inst_type else idx_sel if 'OPTIDX' in inst_type else 'NIFTY'}", {})
            exp_code  = exp_codes.get(exp_sel, "")

            if "OPTIDX" in inst_type:
                df = _get_option_chain(symbol_key, exp_code)
                df["Particular"] = symbol_name
            else:
                # Fetch for each selected stock
                frames = []
                for stk in (selected_stocks[:20] if selected_stocks else []):
                    sym = f"NSE:{stk}-EQ"
                    df_stk = _get_option_chain(sym, exp_code)
                    if not df_stk.empty:
                        df_stk["Particular"] = stk
                        frames.append(df_stk)
                df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

            if df.empty:
                st.warning("No data returned. Check token, expiry, or market hours.")
                return

            # ── Apply filters ─────────────────────────────────────────────────
            # Volume filter
            if "Volume" in df.columns and vol_gt > 0:
                df = df[pd.to_numeric(df["Volume"], errors="coerce").fillna(0) > vol_gt]

            # New OI filter
            if new_oi_only and "OI" in df.columns:
                df = df[pd.to_numeric(df["OI"], errors="coerce").fillna(-1) == 0]

            # Option type filter
            if opt_type_filter == "CE Only" and "Option Type" in df.columns:
                df = df[df["Option Type"].str.upper() == "CE"]
            elif opt_type_filter == "PE Only" and "Option Type" in df.columns:
                df = df[df["Option Type"].str.upper() == "PE"]

            # Sort by volume desc
            if "Volume" in df.columns:
                df = df.sort_values("Volume", ascending=False)

            _SS.bh_result = df.reset_index(drop=True)

    # ── Display results ────────────────────────────────────────────────────────
    if _SS.get("bh_result") is not None and not _SS.bh_result.empty:
        df = _SS.bh_result

        # Build display table
        out_cols = {
            "Particular":   "Particular",
            "Expiry":       "Expiry",
            "Strike Price": "Strike Price",
            "Option Type":  "Option Type",
            "Volume":       "Volume",
            "OI":           "OI",
            "LTP":          "LTP",
        }
        show_cols = [c for c in out_cols if c in df.columns]
        df_show   = df[show_cols].rename(columns=out_cols)

        # Format numbers
        for col in ["Volume","OI"]:
            if col in df_show.columns:
                df_show[col] = pd.to_numeric(df_show[col], errors="coerce").fillna(0).astype(int)

        st.markdown(
            f'<div style="font-size:12px;color:#787b86;margin:8px 0;">'
            f'Showing <b style="color:#d1d4dc;">{len(df_show)}</b> strikes</div>',
            unsafe_allow_html=True)

        st.dataframe(df_show, use_container_width=True, hide_index=True, height=480)

        # ── Export ────────────────────────────────────────────────────────────
        st.markdown("---")
        ec1, ec2 = st.columns(2)

        with ec1:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_show.to_excel(writer, index=False, sheet_name="Bhavcopy")
                from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
                ws  = writer.sheets["Bhavcopy"]
                hf  = PatternFill("solid", fgColor="1A1F2E")
                thin= Side(border_style="thin", color="2A2E39")
                bdr = Border(left=thin,right=thin,top=thin,bottom=thin)
                for cell in ws[1]:
                    cell.font=Font(color="787B86",bold=True); cell.fill=hf
                    cell.border=bdr; cell.alignment=Alignment(horizontal="center")
                for row in ws.iter_rows(min_row=2):
                    for cell in row:
                        cell.fill=PatternFill("solid",fgColor="1E222D")
                        cell.font=Font(color="D1D4DC"); cell.border=bdr
                        cell.alignment=Alignment(horizontal="center")
                for col in ws.columns:
                    ws.column_dimensions[col[0].column_letter].width = min(
                        max(len(str(c.value or "")) for c in col)+4, 20)
            buf.seek(0)
            st.download_button("📥 Export Excel", data=buf,
                               file_name="bhavcopy.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)
        with ec2:
            st.download_button("📄 Export CSV",
                               data=df_show.to_csv(index=False).encode(),
                               file_name="bhavcopy.csv",
                               mime="text/csv", use_container_width=True)
    elif _SS.get("bh_result") is not None:
        st.info("No strikes match the selected filters.")
    else:
        st.markdown("""
        <div style="height:200px;display:flex;align-items:center;justify-content:center;
                    background:#1e222d;border:1px dashed #2a2e39;border-radius:8px;">
          <div style="text-align:center;">
            <div style="font-size:32px;margin-bottom:8px;">📋</div>
            <div style="font-size:13px;color:#787b86;">Select filters above and click Fetch Bhavcopy</div>
          </div>
        </div>""", unsafe_allow_html=True)
