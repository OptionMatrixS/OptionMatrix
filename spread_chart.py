"""
spread_chart.py — Spread Chart + Safety Calculator (embedded below)
The Safety Calculator reads legs directly from this page's inputs.
"""
import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import io
from data_helpers import (
    get_index_expiries, get_index_strikes,
    get_option_price, generate_spread_ohlcv,
    calc_greeks_for_legs, TF_MAP,
)
from fyers_client import get_live_quote

_SS = st.session_state

def _init():
    for k,v in [("sp_n_legs",2),("sp_chart_type","Candlestick"),
                ("sp_tf","1m"),("sp_result",None),("sp_df",None),("sp_legs_live",[])]:
        if k not in _SS: _SS[k] = v

def _load_expiries(index):
    ck = f"expiries_{index}"
    if _SS.get(ck): return list(_SS[ck].keys()), None
    try:
        exps = get_index_expiries(index)
        return exps, None
    except Exception as e:
        return [], str(e)

def _load_strikes(index, expiry):
    if not expiry: return [], "No expiry."
    ck = f"strikes_{index}_{expiry}"
    if _SS.get(ck): return _SS[ck], None
    try:
        strikes = get_index_strikes(index, expiry)
        return strikes, None
    except Exception as e:
        return [], str(e)

def _validate_ui(legs):
    errs = []
    for i,l in enumerate(legs):
        if not l.get("expiry"): errs.append(f"Leg {i+1}: Expiry not selected.")
        if not l.get("strike") or l["strike"]<=0: errs.append(f"Leg {i+1}: Strike not selected.")
    return errs

def _build_chart(df, result, chart_type, tf):
    title = "SPREAD CHART"
    if result and result.get("legs") and len(result["legs"]) >= 2:
        l = result["legs"]
        title = (f"{l[0]['index']} {l[0]['strike']}{l[0]['cp']} {l[0]['bs'][0]}"
                 f" / {l[1]['index']} {l[1]['strike']}{l[1]['cp']} {l[1]['bs'][0]}  [{tf}]")
    fig = go.Figure()
    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=df["time"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="Spread",
            increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
            line=dict(width=1), whiskerwidth=0.3))
    else:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["close"], mode="lines", name="Spread",
            line=dict(color="#2962ff", width=1.5),
            fill="tozeroy", fillcolor="rgba(41,98,255,0.07)"))
    fig.add_hline(y=0, line=dict(color="#363a45", width=1, dash="dot"))
    last = df["close"].iloc[-1]
    fig.add_annotation(x=df["time"].iloc[-1], y=last, text=f" {last:.2f}",
        showarrow=False, font=dict(size=11, color="#fff"),
        bgcolor="#26a69a" if last >= 0 else "#ef5350", borderpad=4, xanchor="left")
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#d1d4dc"), x=0),
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        xaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   rangeslider=dict(visible=False), showline=False, zeroline=False, fixedrange=False),
        yaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   showline=False, zeroline=False, side="right", fixedrange=False),
        margin=dict(l=10,r=68,t=36,b=28), height=380,
        hovermode="x unified", dragmode="pan",
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39", font=dict(size=11, color="#d1d4dc")))
    return fig

# ── Safety Calculator (embedded) ──────────────────────────────────────────────
def _nearest(strikes, target):
    if not strikes: return target
    return min(strikes, key=lambda x: abs(x - target))

def _render_safety(legs):
    st.markdown("---")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">'
        '<div style="font-size:16px;font-weight:600;color:#d1d4dc;">🛡️ Safety Calculator</div>'
        '<div style="font-size:11px;color:#787b86;padding:2px 8px;background:#1e222d;'
        'border:1px solid #2a2e39;border-radius:8px;">Auto-linked to legs above</div></div>',
        unsafe_allow_html=True)
    st.markdown(
        '<div style="font-size:11px;color:#787b86;margin-bottom:10px;">'
        'Row 0 = your selected strikes. ±N rows offset by the Strike Interval you set per leg.</div>',
        unsafe_allow_html=True)

    n_legs = len(legs)
    sc_col, tbl_col = st.columns([1, 3], gap="medium")

    with sc_col:
        # Per-leg interval inputs
        st.markdown('<div class="sec-header">Strike Interval per Leg</div>', unsafe_allow_html=True)
        diffs = []
        for i, leg in enumerate(legs):
            default_diff = 100 if leg["index"] in ("NIFTY","BANKNIFTY") else 500
            d = st.number_input(
                f"LEG {i+1} ({leg['index']}) interval",
                min_value=1, max_value=10000,
                value=int(_SS.get(f"sc_diff_{i}", default_diff)),
                step=default_diff, key=f"sc_diff_{i}",
                label_visibility="visible")
            diffs.append(d)
        n_rows = st.number_input("Rows above/below", 1, 10, 3, key="sc_n_rows")
        build  = st.button("🛡️  Build Safety Matrix", use_container_width=True, type="primary", key="sc_build")

    with tbl_col:
        # Auto-build or on button
        sig = str(legs) + str(diffs) + str(n_rows)
        if build or _SS.get("sc_last_sig") != sig:
            _SS.sc_last_sig = sig
            # Build matrix
            matrix_rows = []
            for offset in range(-int(n_rows), int(n_rows) + 1):
                row = {"SERIES": f"{offset:+d}" if offset != 0 else "0 (BASE)"}
                strikes_this = []
                for i, leg in enumerate(legs):
                    # Get actual strikes for this index+expiry
                    ck = f"strikes_{leg['index']}_{leg['expiry']}"
                    avail = _SS.get(ck, [])
                    target  = leg["strike"] + offset * diffs[i]
                    nearest = _nearest(avail, target) if avail else target
                    row[f"LEG {i+1}"] = nearest
                    strikes_this.append(nearest)

                # Fetch live spread price for this row of strikes
                bid_t = ask_t = ltp_t = 0.0
                for i, leg in enumerate(legs):
                    try:
                        q    = get_live_quote(leg["index"], strikes_this[i], leg["expiry"], leg["cp"])
                        sign = 1 if leg["bs"] == "Buy" else -1
                        bid_t += sign * q["bid"]  * leg["ratio"]
                        ask_t += sign * q["ask"]  * leg["ratio"]
                        ltp_t += sign * q["ltp"]  * leg["ratio"]
                    except Exception:
                        pass
                row["BID"] = round(bid_t, 2)
                row["ASK"] = round(ask_t, 2)
                row["LTP"] = round(ltp_t, 2)
                matrix_rows.append((offset, row))

            _SS.sc_matrix = matrix_rows

        if not _SS.get("sc_matrix"):
            st.info("Configure legs above and click Build Safety Matrix.")
            return

        # ── Render table ──────────────────────────────────────────────────────
        hdr_cols = ["SERIES"] + [f"LEG {i+1}" for i in range(n_legs)] + ["BID","ASK","LTP"]
        # Difference info row
        diff_info = {"SERIES": "INTERVAL"}
        for i in range(n_legs): diff_info[f"LEG {i+1}"] = diffs[i]
        diff_info["BID"] = diff_info["ASK"] = diff_info["LTP"] = "—"

        header_html = "".join(
            f'<th style="padding:5px 10px;font-size:10px;color:#787b86;text-align:center;'
            f'border-bottom:1px solid #2a2e39;white-space:nowrap;">{c}</th>'
            for c in hdr_cols)

        # Diff row
        diff_cells = "".join(
            f'<td style="padding:5px 10px;font-size:11px;font-weight:700;color:#ff9800;'
            f'text-align:center;background:#1a1f2e;">{diff_info[c]}</td>'
            for c in hdr_cols)

        rows_html = ""
        for offset, row in _SS.sc_matrix:
            is_base = (offset == 0)
            bg      = "#162040" if is_base else "#1e222d"
            bl      = "border-left:3px solid #2962ff;" if is_base else "border-left:3px solid transparent;"
            cells   = ""
            for c in hdr_cols:
                val = row[c]
                if c == "SERIES":
                    fw  = "700" if is_base else "400"
                    clr = "#2962ff" if is_base else "#787b86"
                    cells += (f'<td style="padding:6px 10px;font-size:11px;font-weight:{fw};'
                               f'color:{clr};text-align:center;">{val}</td>')
                elif c.startswith("LEG"):
                    fw  = "600" if is_base else "400"
                    clr = "#ffffff" if is_base else "#d1d4dc"
                    cells += (f'<td style="padding:6px 10px;font-size:12px;font-weight:{fw};'
                               f'color:{clr};font-family:\'JetBrains Mono\',monospace;'
                               f'text-align:center;">{val}</td>')
                else:
                    try:
                        fv  = float(val)
                        clr = "#26a69a" if fv >= 0 else "#ef5350"
                        fw  = "600" if is_base else "400"
                        txt = f"{fv:+.2f}"
                    except Exception:
                        clr = "#787b86"; fw = "400"; txt = str(val)
                    cells += (f'<td style="padding:6px 10px;font-size:12px;font-weight:{fw};'
                               f'color:{clr};font-family:\'JetBrains Mono\',monospace;'
                               f'text-align:center;">{txt}</td>')
            rows_html += f'<tr style="background:{bg};{bl}border-bottom:1px solid #2a2e39;">{cells}</tr>'

        st.markdown(
            f'<div style="overflow-x:auto;border:1px solid #2a2e39;border-radius:8px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead>'
            f'<tr style="background:#1a1f2e;">{diff_cells}</tr>'
            f'<tr style="background:#1a1f2e;">{header_html}</tr>'
            f'</thead><tbody>{rows_html}</tbody></table></div>',
            unsafe_allow_html=True)

        # Export
        if st.button("📥 Export Safety Matrix (Excel)", key="sc_export"):
            rows_flat = [r for _, r in _SS.sc_matrix]
            df_exp    = pd.DataFrame(rows_flat)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_exp.to_excel(writer, index=False, sheet_name="SafetyMatrix")
            buf.seek(0)
            st.download_button("Download", data=buf,
                               file_name="safety_matrix.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render():
    _init()
    st.markdown('<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:8px;">📊 Spread Chart</div>',
                unsafe_allow_html=True)
    # ── Refresh controls ─────────────────────────────────────────────────────
    _rc1, _rc2, _rc3 = st.columns([2,1,1])
    with _rc2:
        auto_ref = st.toggle("🔴 Auto Refresh", value=False, key="sc_auto_ref",
                              help="Refreshes every 30 seconds")
    with _rc3:
        if st.button("🔄 Refresh Now", key="sc_ref_now", use_container_width=True):
            st.rerun()
    if auto_ref:
        import time as _time
        _time.sleep(30)
        st.rerun()



    # ── Chart ──────────────────────────────────────────────────────────────────
    if _SS.sp_df is not None:
        st.plotly_chart(_build_chart(_SS.sp_df, _SS.sp_result, _SS.sp_chart_type, _SS.sp_tf),
                        use_container_width=True,
                        config={"displayModeBar":True,"displaylogo":False,"scrollZoom":True,
                                "modeBarButtonsToRemove":["autoScale2d","lasso2d","select2d"]})
        if _SS.sp_result:
            r = _SS.sp_result; sv = r["spread"]
            items = [
                ("SPREAD",     f"{sv:+.2f}",    "#26a69a" if sv>=0 else "#ef5350"),
                ("NET PREM",   f"{r['net_prem']:+.2f}", "#d1d4dc"),
                ("MAX PROFIT", "Unlimited" if r['max_profit'] is None else f"{r['max_profit']:.2f}", "#26a69a"),
                ("MAX LOSS",   f"{r['max_loss']:.2f}" if r['max_loss'] else "—", "#ef5350"),
                ("BREAKEVEN",  f"{r['be']:.0f}" if r['be'] else "—", "#d1d4dc"),
            ]
            for col,(lbl,val,clr) in zip(st.columns(5),items):
                with col:
                    st.markdown(f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                                f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                                unsafe_allow_html=True)
    else:
        st.markdown('<div style="height:160px;display:flex;align-items:center;justify-content:center;'
                    'background:#1e222d;border:1px solid #2a2e39;border-radius:8px;margin-bottom:12px;">'
                    '<div style="font-size:13px;color:#787b86;">Configure legs below and click Calculate</div>'
                    '</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="sec-header">Strategy Builder</div>', unsafe_allow_html=True)

    c1,c2,c3 = st.columns(3)
    with c1: _SS.sp_n_legs     = st.selectbox("Legs",list(range(2,7)),index=_SS.sp_n_legs-2,key="sp_legs_sel")
    with c2: _SS.sp_chart_type = st.selectbox("Chart Type",["Candlestick","Line"],key="sp_ct_sel")
    with c3: _SS.sp_tf         = st.selectbox("Timeframe",list(TF_MAP.keys()),key="sp_tf_sel")

    n    = _SS.sp_n_legs
    legs = []
    cols_legs = st.columns(n)
    for i in range(n):
        with cols_legs[i]:
            st.markdown(f'<div style="font-size:10px;color:#787b86;margin-bottom:6px;background:#2a2e39;'
                        f'padding:2px 8px;border-radius:10px;display:inline-block;">LEG {i+1}</div>',
                        unsafe_allow_html=True)
            idx = st.selectbox("Index",["NIFTY","SENSEX","BANKNIFTY"],
                               key=f"sp_idx_{i}",label_visibility="collapsed")
            exps, exp_err = _load_expiries(idx)
            if exp_err or not exps:
                st.markdown('<div style="font-size:11px;color:#ff9800;">⏳ Loading expiries…</div>',
                            unsafe_allow_html=True)
                if st.button("🔄",key=f"re_exp_{i}"):
                    _SS.pop(f"expiries_{idx}",None); st.rerun()
                legs.append(dict(index=idx,strike=0,expiry="",cp="CE",
                                 bs="Buy" if i%2==0 else "Sell",ratio=1,ltp=0.0,net=0.0))
                continue
            expiry = st.selectbox("Expiry",exps,key=f"sp_exp_{i}",label_visibility="collapsed")
            strikes, str_err = _load_strikes(idx, expiry)
            if str_err or not strikes:
                st.markdown('<div style="font-size:11px;color:#ff9800;">⏳ Loading strikes…</div>',
                            unsafe_allow_html=True)
                if st.button("🔄",key=f"re_str_{i}"):
                    _SS.pop(f"strikes_{idx}_{expiry}",None); st.rerun()
                legs.append(dict(index=idx,strike=0,expiry=expiry,cp="CE",
                                 bs="Buy" if i%2==0 else "Sell",ratio=1,ltp=0.0,net=0.0))
                continue
            atm    = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx,strikes[len(strikes)//2])
            def_s  = min(strikes, key=lambda x: abs(x-atm))
            cur    = _SS.get(f"sp_strike_{i}")
            didx   = strikes.index(cur) if cur in strikes else strikes.index(def_s)
            strike = st.selectbox("Strike",strikes,index=didx,
                                  key=f"sp_strike_{i}",label_visibility="collapsed")
            cp     = st.selectbox("CE/PE",["CE","PE"],key=f"sp_cp_{i}",label_visibility="collapsed")
            bs     = st.selectbox("Buy/Sell",["Buy","Sell"],
                                  index=0 if i%2==0 else 1,
                                  key=f"sp_bs_{i}",label_visibility="collapsed")
            ratio  = st.number_input("Ratio",1,10,1,key=f"sp_ratio_{i}",label_visibility="collapsed")
            ltp = signed = 0.0
            try:
                ltp    = get_option_price(idx, strike, expiry, cp)
                signed = ltp*ratio if bs=="Buy" else -ltp*ratio
                clr    = "#26a69a" if signed>=0 else "#ef5350"
                st.markdown(f'<div style="font-size:11px;color:#787b86;margin-top:3px;">'
                            f'LTP: <span style="color:#d1d4dc;">{ltp:.2f}</span>'
                            f' &nbsp; Net: <span style="color:{clr};">{signed:+.2f}</span></div>',
                            unsafe_allow_html=True)
            except Exception:
                st.markdown('<div style="font-size:10px;color:#787b86;margin-top:3px;">LTP: —</div>',
                            unsafe_allow_html=True)
            legs.append(dict(index=idx,strike=strike,expiry=expiry,
                             cp=cp,bs=bs,ratio=ratio,ltp=ltp,net=round(signed,2)))

    valid_legs = [l for l in legs if l["expiry"] and l["strike"]>0]
    _SS.sp_legs_live = valid_legs
    st.markdown(f'<div style="font-size:10px;color:#26a69a;margin:6px 0;">✓ {len(valid_legs)}/{n} legs ready</div>',
                unsafe_allow_html=True)

    show_greeks = st.checkbox("Show Greeks", value=False, key="sp_show_greeks")
    ui_errs     = _validate_ui(legs)

    if ui_errs:
        st.warning("Complete all leg inputs:\n\n" + "\n".join(f"• {e}" for e in ui_errs))
    else:
        if st.button("⚡  Calculate & Plot", use_container_width=True, type="primary"):
            with st.spinner("Fetching live prices…"):
                fresh_legs=[]; ok=True
                for leg in legs:
                    try:
                        ltp  = get_option_price(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
                        sign = 1 if leg["bs"]=="Buy" else -1
                        fresh_legs.append({**leg,"ltp":ltp,"net":round(sign*ltp*leg["ratio"],2)})
                    except Exception as e:
                        st.error(f"LTP Leg {legs.index(leg)+1}: {e}"); ok=False; break
            if ok:
                buys  = [l for l in fresh_legs if l["bs"]=="Buy"]
                sells = [l for l in fresh_legs if l["bs"]=="Sell"]
                spread   = sum(l["ltp"]*l["ratio"] for l in buys) - sum(l["ltp"]*l["ratio"] for l in sells)
                net_prem = sum(l["net"] for l in fresh_legs)
                max_profit = max_loss = be = None
                if buys and sells:
                    sd = abs(buys[0]["strike"]-sells[0]["strike"])
                    max_profit = sd-abs(spread) if sd>abs(spread) else None
                    max_loss   = abs(spread)
                    be = buys[0]["strike"]+spread if buys[0]["cp"]=="CE" else buys[0]["strike"]-spread
                with st.spinner("Fetching candles…"):
                    try:
                        tf_min    = TF_MAP[_SS.sp_tf]
                        _SS.sp_df = generate_spread_ohlcv(fresh_legs, tf_minutes=tf_min)
                        _SS.sp_result = dict(spread=round(spread,2),net_prem=round(net_prem,2),
                                              max_profit=max_profit,max_loss=max_loss,be=be,legs=fresh_legs)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Candle fetch failed: {e}")

    if show_greeks and valid_legs and any(l["ltp"]>0 for l in valid_legs):
        st.markdown('<div class="sec-header" style="margin-top:12px;">Net Greeks</div>', unsafe_allow_html=True)
        with st.spinner("Calculating…"):
            try:
                g = calc_greeks_for_legs(valid_legs)
                hi_avg = lo_avg = None
                if _SS.sp_df is not None:
                    closes = _SS.sp_df["close"].dropna()
                    if len(closes)>=5: hi_avg=round(closes.nlargest(5).mean(),2); lo_avg=round(closes.nsmallest(5).mean(),2)
                metrics = [
                    ("NET DELTA",f"{g['delta']:+.4f}","#2962ff"),
                    ("NET GAMMA",f"{g['gamma']:+.6f}","#ff9800"),
                    ("NET VEGA",f"{g['vega']:+.4f}","#9c27b0"),
                    ("NET THETA",f"{g['theta']:+.4f}","#ef5350"),
                    ("NET IV",f"{g['net_iv']:.2f}%","#26a69a"),
                    ("AVG HIGH",f"{hi_avg:.2f}" if hi_avg else "—","#26a69a"),
                    ("AVG LOW",f"{lo_avg:.2f}" if lo_avg else "—","#ef5350"),
                ]
                for col,(lbl,val,clr) in zip(st.columns(7),metrics):
                    with col:
                        st.markdown(f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                                    f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                                    unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Greeks failed: {e}")

    if _SS.sp_result:
        r=_SS.sp_result; sv=r["spread"]
        st.markdown("---")
        sv_col,_=st.columns([1,3])
        with sv_col:
            st.markdown(f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:8px;'
                        f'padding:14px;text-align:center;">'
                        f'<div style="font-size:10px;color:#787b86;text-transform:uppercase;">Spread Value</div>'
                        f'<div style="font-size:26px;font-weight:600;'
                        f'color:{"#26a69a" if sv>=0 else "#ef5350"};">{sv:+.2f}</div></div>',
                        unsafe_allow_html=True)
        df_show=pd.DataFrame(r["legs"])[["index","strike","expiry","cp","bs","ratio","ltp","net"]]
        df_show.columns=["Index","Strike","Expiry","C/P","B/S","Ratio","LTP","Net"]
        st.dataframe(df_show,use_container_width=True,hide_index=True)

    # ── Safety Calculator embedded below ─────────────────────────────────────
    if valid_legs:
        _render_safety(valid_legs)
