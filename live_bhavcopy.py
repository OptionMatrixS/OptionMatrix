"""live_bhavcopy.py — Tab 8: live option-chain bhavcopy snapshot."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

import styles
import fyers_client as fc

P = styles.PALETTE

OPTIDX = ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"]

# A representative set of liquid NSE F&O single stocks. (NSE's full F&O list
# changes periodically; extend this as needed.)
FNO_STOCKS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",
    "KOTAKBANK", "ITC", "LT", "HINDUNILVR", "BHARTIARTL", "BAJFINANCE",
    "BAJAJFINSV", "MARUTI", "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "HINDALCO",
    "WIPRO", "HCLTECH", "TECHM", "ADANIENT", "ADANIPORTS", "ASIANPAINT",
    "TITAN", "NESTLEIND", "ULTRACEMCO", "GRASIM", "POWERGRID", "NTPC",
    "ONGC", "COALINDIA", "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB",
    "APOLLOHOSP", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "M&M", "BPCL",
    "IOC", "GAIL", "DLF", "PIDILITIND", "HAVELLS", "SIEMENS", "ABB",
    "INDUSINDBK", "PNB", "BANKBARODA", "CANBK", "IDFCFIRSTB", "FEDERALBNK",
    "AUBANK", "SBILIFE", "HDFCLIFE", "ICICIPRULI", "ICICIGI", "SHRIRAMFIN",
    "CHOLAFIN", "MUTHOOTFIN", "LICHSGFIN", "TVSMOTOR", "ASHOKLEY", "BOSCHLTD",
    "BALKRISIND", "MRF", "VEDL", "NATIONALUM", "SAIL", "JINDALSTEL",
    "TATACONSUM", "BRITANNIA", "DABUR", "GODREJCP", "MARICO", "COLPAL",
    "BIOCON", "LUPIN", "AUROPHARMA", "TORNTPHARM", "ZYDUSLIFE", "GLENMARK",
    "TRENT", "DMART", "NAUKRI", "ZOMATO", "PAYTM", "PERSISTENT", "COFORGE",
    "LTIM", "MPHASIS", "INDIGO", "IRCTC", "BEL", "HAL", "BHEL", "IEX",
]


def _ltp(item):
    return fc._to_float(item.get("ltp") or item.get("last_price") or item.get("lp"))


def _flatten(chain, particular, expiry_label):
    rows = []
    for it in chain:
        ot = str(it.get("option_type") or "").upper()
        if ot not in ("CE", "PE"):
            continue
        strike = fc._to_float(it.get("strike_price"))
        if strike <= 0:
            continue
        rows.append({
            "Particular": particular, "Expiry": expiry_label,
            "Strike": int(strike), "Type": ot,
            "Volume": int(fc._to_float(it.get("volume"))),
            "OI": int(fc._to_float(it.get("oi"))),
            "OI Change": int(fc._to_float(it.get("oichng")
                                          or it.get("oi_change"))),
            "LTP": round(_ltp(it), 2)})
    return rows


def _stock_chain_rows(sym):
    """Fetch nearest-expiry chain for a single F&O stock underlying."""
    fc.get_fyers_client()  # ensure token
    underlying = f"NSE:{sym}-EQ"
    resp = fc.get_fyers_client().optionchain(
        data={"symbol": underlying, "strikecount": 0, "timestamp": ""})
    data = (resp or {}).get("data", {})
    chain = data.get("optionsChain") or []
    edata = data.get("expiryData") or []
    exp_label = ""
    if edata:
        d = fc._parse_expiry_date(edata[0])
        exp_label = f"{d.day:02d} {fc._MONTHS[d.month-1]} {d.strftime('%y')}"
    return _flatten(chain, sym, exp_label)


def render(user):
    c = st.columns([1, 1.4, 1, 1])
    segment = c[0].selectbox("Segment", ["OPTIDX", "OPTSTK"], key="bc_seg")

    rows = []
    if segment == "OPTIDX":
        index = c[1].selectbox("Index", OPTIDX, key="bc_idx")
        try:
            exps = fc.get_expiries(index)
        except Exception as e:
            st.error(f"Expiry fetch failed: {e}")
            return
        labels = [e["label"] for e in exps]
        exp = c[2].selectbox("Expiry", labels or ["—"], key="bc_exp")
        ot_filter = c[3].selectbox("Type", ["All", "CE", "PE"], key="bc_ot")
        f1, f2 = st.columns([1, 1])
        vol_min = f1.number_input("Volume >", 0, 10_000_000, 0, step=100,
                                  key="bc_vol")
        new_oi = f2.checkbox("New OI only (OI change ≠ 0)", key="bc_newoi")

        if st.button("📋 Load Bhavcopy", key="bc_load"):
            e = next((x for x in exps if x["label"] == exp), None)
            if not e:
                st.warning("Pick an expiry.")
                return
            try:
                chain = fc.get_chain(index, e["epoch"])
            except Exception as ex:
                st.error(f"Chain fetch failed: {ex}")
                return
            rows = _flatten(chain, index, exp)
            _show(rows, ot_filter, vol_min, new_oi, f"{index}_{exp}")

    else:  # OPTSTK
        select_all = c[1].checkbox("Select ALL F&O stocks (slow)", key="bc_all")
        ot_filter = c[2].selectbox("Type", ["All", "CE", "PE"], key="bc_sot")
        vol_min = c[3].number_input("Volume >", 0, 10_000_000, 0, step=100,
                                    key="bc_svol")
        picks = st.multiselect("Stocks", FNO_STOCKS,
                               default=["RELIANCE", "SBIN", "TATAMOTORS"],
                               key="bc_stocks", disabled=select_all)
        new_oi = st.checkbox("New OI only (OI change ≠ 0)", key="bc_snewoi")
        chosen = FNO_STOCKS if select_all else picks

        if st.button("📋 Load Bhavcopy", key="bc_sload"):
            if not chosen:
                st.warning("Pick at least one stock.")
                return
            if len(chosen) > 15:
                st.info(f"Fetching {len(chosen)} chains — this can take a while.")
            prog = st.progress(0.0)
            for i, sym in enumerate(chosen):
                try:
                    rows.extend(_stock_chain_rows(sym))
                except Exception:
                    pass  # skip a stock whose chain isn't available
                prog.progress((i + 1) / len(chosen))
            prog.empty()
            _show(rows, ot_filter, vol_min, new_oi, "fno_stocks")


def _show(rows, ot_filter, vol_min, new_oi, fname):
    if not rows:
        st.info("No option rows returned.")
        return
    df = pd.DataFrame(rows)
    if ot_filter != "All":
        df = df[df["Type"] == ot_filter]
    if vol_min > 0:
        df = df[df["Volume"] > vol_min]
    if new_oi:
        df = df[df["OI Change"] != 0]
    if df.empty:
        st.info("No rows match the filters.")
        return
    df = df.sort_values("Volume", ascending=False).reset_index(drop=True)
    st.caption(f"{len(df):,} rows")
    st.dataframe(df, use_container_width=True, hide_index=True, height=460)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="Bhavcopy")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Excel", buf.getvalue(), file_name=f"bhavcopy_{fname}.xlsx",
                       key="bc_xl", mime="application/vnd.openxmlformats-"
                       "officedocument.spreadsheetml.sheet")
    c2.download_button("⬇️ CSV", df.to_csv(index=False).encode(),
                       file_name=f"bhavcopy_{fname}.csv", key="bc_csv",
                       mime="text/csv")
