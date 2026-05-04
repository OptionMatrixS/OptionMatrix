"""
spread_chart.py — Spread Chart + Safety Calculator
Live mode: updates every N seconds using st.empty() loop (TradingView-style).
Historical mode: fetches today's candle history from Fyers.
"""
import sys, os, time
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
from fyers_client import get_live_quote, get_live_ltp

_SS = st.session_state

# ─── init ─────────────────────────────────────────────────────────────────────
def _init():
    for k, v in [
        ("sp_n_legs", 2), ("sp_chart_type", "Candlestick"),
        ("sp_tf", "1m"), ("sp_result", None), ("sp_df", None),
        ("sp_legs_live", []), ("sp_live_hist", []),
        ("sp_live_running", False),
    ]:
        if k not in _SS:
            _SS[k] = v

# ─── expiry/strike loaders ────────────────────────────────────────────────────
def _load_expiries(index):
    ck = f"expiries_{index}"
    if _SS.get(ck): return list(_SS[ck].keys()), None
    try:    return get_index_expiries(index), None
    except Exception as e: return [], str(e)

def _load_strikes(index, expiry):
    if not expiry: return [], "No expiry."
    ck = f"strikes_{index}_{expiry}"
    if _SS.get(ck): return _SS[ck], None
    try:    return get_index_strikes(index, expiry), None
    except Exception as e: return [], str(e)

# ─── compute live spread value ────────────────────────────────────────────────
def _live_spread_value(legs) -> float:
    """Fetch live LTPs and return net spread value."""
    total = 0.0
    for leg in legs:
        try:
            ltp  = get_live_ltp(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
            sign = 1 if leg["bs"] == "Buy" else -1
            total += sign * ltp * leg["ratio"]
        except Exception:
            pass
    return round(total, 2)

# ─── build chart from history ─────────────────────────────────────────────────
def _build_chart(hist: list, result: dict, chart_type: str, tf: str):
    """Build Plotly chart from list of (time, value) points."""
    if not hist:
        return go.Figure()

    df   = pd.DataFrame(hist, columns=["time", "value"])
    last = df["value"].iloc[-1]

    title = "SPREAD — LIVE"
    if result and result.get("legs") and len(result["legs"]) >= 2:
        lgs = result["legs"]
        title = (f"{lgs[0]['index']} {lgs[0]['strike']}{lgs[0]['cp']} {lgs[0]['bs'][0]}"
                 f" / {lgs[1]['index']} {lgs[1]['strike']}{lgs[1]['cp']} {lgs[1]['bs'][0]}"
                 f"  [{tf}]")

    fig = go.Figure()

    # Colour based on direction from first tick
    clr = "#26a69a" if last >= df["value"].iloc[0] else "#ef5350"

    if chart_type == "Candlestick" and len(df) >= 2:
        # Group ticks into OHLC bars by minute
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time").resample("1min")["value"].ohlc().dropna().reset_index()
        if not df.empty:
            fig.add_trace(go.Candlestick(
                x=df["time"], open=df["open"], high=df["high"],
                low=df["low"],  close=df["close"],
                name="Spread",
                increasing_line_color="#26a69a",  increasing_fillcolor="#26a69a",
                decreasing_line_color="#ef5350",  decreasing_fillcolor="#ef5350",
                line=dict(width=1), whiskerwidth=0.3))
            last = float(df["close"].iloc[-1])
    else:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["value"], mode="lines",
            name="Spread",
            line=dict(color=clr, width=1.8),
            fill="tozeroy",
            fillcolor=f"rgba({'38,166,154' if last>=0 else '239,83,80'},0.07)"))

    fig.add_hline(y=0, line=dict(color="#363a45", width=1, dash="dot"))

    # Last-value label
    if not df.empty:
        last_x = df["time"].iloc[-1] if "time" in df.columns else None
        if last_x is not None:
            fig.add_annotation(
                x=last_x, y=last,
                text=f"  {last:+.2f}",
                showarrow=False,
                font=dict(size=11, color="#fff"),
                bgcolor="#26a69a" if last >= 0 else "#ef5350",
                borderpad=4, xanchor="left")

    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#d1d4dc"), x=0),
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        xaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   rangeslider=dict(visible=False),
                   showline=False, zeroline=False, fixedrange=False),
        yaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   showline=False, zeroline=False, side="right", fixedrange=False),
        margin=dict(l=10, r=68, t=36, b=28), height=400,
        hovermode="x unified", dragmode="pan",
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                        font=dict(size=11, color="#d1d4dc")))
    return fig

# ─── historical candle chart (for chart mode) ─────────────────────────────────
def _build_candle_chart(df: pd.DataFrame, result: dict, chart_type: str, tf: str):
    title = "SPREAD CHART"
    if result and result.get("legs") and len(result["legs"]) >= 2:
        lgs = result["legs"]
        title = (f"{lgs[0]['index']} {lgs[0]['strike']}{lgs[0]['cp']} {lgs[0]['bs'][0]}"
                 f" / {lgs[1]['index']} {lgs[1]['strike']}{lgs[1]['cp']} {lgs[1]['bs'][0]}"
                 f"  [{tf}]")
    fig = go.Figure()
    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=df["time"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="Spread",
            increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
            line=dict(width=1), whiskerwidth=0.3))
    else:
        last = df["close"].iloc[-1]
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["close"], mode="lines", name="Spread",
            line=dict(color="#2962ff", width=1.5),
            fill="tozeroy",
            fillcolor=f"rgba({'38,166,154' if last>=0 else '239,83,80'},0.07)"))
    fig.add_hline(y=0, line=dict(color="#363a45", width=1, dash="dot"))
    last = df["close"].iloc[-1]
    fig.add_annotation(x=df["time"].iloc[-1], y=last, text=f"  {last:+.2f}",
        showarrow=False, font=dict(size=11, color="#fff"),
        bgcolor="#26a69a" if last >= 0 else "#ef5350", borderpad=4, xanchor="left")
    fig.update_layout(
        title=dict(text=title, font=dict(size=12, color="#d1d4dc"), x=0),
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        xaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   rangeslider=dict(visible=False), showline=False, zeroline=False),
        yaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   showline=False, zeroline=False, side="right"),
        margin=dict(l=10, r=68, t=36, b=28), height=400,
        hovermode="x unified", dragmode="pan",
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                        font=dict(size=11, color="#d1d4dc")))
    return fig

# ─── Safety Calculator ────────────────────────────────────────────────────────
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
        'Row 0 = your selected strikes. ±N rows offset by Strike Interval per leg.</div>',
        unsafe_allow_html=True)

    n_legs = len(legs)
    sc_col, tbl_col = st.columns([1, 3], gap="medium")

    with sc_col:
        st.markdown('<div class="sec-header">Strike Interval per Leg</div>', unsafe_allow_html=True)
        diffs = []
        for i, leg in enumerate(legs):
            default_diff = 100 if leg["index"] in ("NIFTY","BANKNIFTY") else 500
            d = st.number_input(
                f"LEG {i+1} ({leg['index']}) interval",
                min_value=1, max_value=10000,
                value=int(_SS.get(f"sc_diff_{i}", default_diff)),
                step=default_diff, key=f"sc_diff_{i}")
            diffs.append(d)
        n_rows = st.number_input("Rows above/below", 1, 10, 3, key="sc_n_rows")
        build  = st.button("🛡️ Build Safety Matrix", use_container_width=True,
                            type="primary", key="sc_build")

    with tbl_col:
        sig = str([(l["index"],l["strike"],l["expiry"],l["cp"],l["bs"]) for l in legs]) + str(diffs) + str(n_rows)
        if build or _SS.get("sc_last_sig") != sig:
            _SS.sc_last_sig = sig
            matrix_rows = []
            for offset in range(-int(n_rows), int(n_rows) + 1):
                row_d = {"SERIES": f"{offset:+d}" if offset != 0 else "0 (BASE)"}
                strikes_this = []
                for i, leg in enumerate(legs):
                    ck     = f"strikes_{leg['index']}_{leg['expiry']}"
                    avail  = _SS.get(ck, [])
                    target = leg["strike"] + offset * diffs[i]
                    nearest= _nearest(avail, target) if avail else target
                    row_d[f"LEG {i+1}"] = nearest
                    strikes_this.append(nearest)
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
                row_d["BID"] = round(bid_t, 2)
                row_d["ASK"] = round(ask_t, 2)
                row_d["LTP"] = round(ltp_t, 2)
                matrix_rows.append((offset, row_d))
            _SS.sc_matrix = matrix_rows

        if not _SS.get("sc_matrix"):
            st.info("Configure legs above and click Build Safety Matrix.")
            return

        hdr_cols = ["SERIES"] + [f"LEG {i+1}" for i in range(n_legs)] + ["BID","ASK","LTP"]
        diff_info = {"SERIES": "INTERVAL"}
        for i in range(n_legs): diff_info[f"LEG {i+1}"] = diffs[i]
        diff_info.update({"BID":"—","ASK":"—","LTP":"—"})

        header_html = "".join(
            f'<th style="padding:5px 10px;font-size:10px;color:#787b86;text-align:center;'
            f'border-bottom:1px solid #2a2e39;white-space:nowrap;">{col}</th>'
            for col in hdr_cols)
        diff_cells = "".join(
            f'<td style="padding:5px 10px;font-size:11px;font-weight:700;color:#ff9800;'
            f'text-align:center;background:#1a1f2e;">{diff_info.get(col,"")}</td>'
            for col in hdr_cols)

        rows_html = ""
        for offset, row_d in _SS.sc_matrix:
            is_base = (offset == 0)
            bg = "#162040" if is_base else "#1e222d"
            bl = "border-left:3px solid #2962ff;" if is_base else "border-left:3px solid transparent;"
            cells = ""
            for col in hdr_cols:
                val = row_d.get(col, "")
                if col == "SERIES":
                    fw  = "700" if is_base else "400"
                    clr = "#2962ff" if is_base else "#787b86"
                    cells += (f'<td style="padding:6px 10px;font-size:11px;font-weight:{fw};'
                              f'color:{clr};text-align:center;">{val}</td>')
                elif col.startswith("LEG"):
                    fw  = "600" if is_base else "400"
                    clr = "#ffffff" if is_base else "#d1d4dc"
                    cells += (f'<td style="padding:6px 10px;font-size:12px;font-weight:{fw};'
                              f'color:{clr};font-family:"JetBrains Mono",monospace;'
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
                              f'color:{clr};font-family:"JetBrains Mono",monospace;'
                              f'text-align:center;">{txt}</td>')
            rows_html += (f'<tr style="background:{bg};{bl}'
                          f'border-bottom:1px solid #2a2e39;">{cells}</tr>')

        st.markdown(
            f'<div style="overflow-x:auto;border:1px solid #2a2e39;border-radius:8px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr style="background:#1a1f2e;">{diff_cells}</tr>'
            f'<tr style="background:#1a1f2e;">{header_html}</tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>',
            unsafe_allow_html=True)

        if st.button("📥 Export Safety Matrix (Excel)", key="sc_export"):
            rows_flat = [r for _, r in _SS.sc_matrix]
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                pd.DataFrame(rows_flat).to_excel(writer, index=False, sheet_name="Safety")
            buf.seek(0)
            st.download_button("Download", data=buf, file_name="safety_matrix.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDER
# ─────────────────────────────────────────────────────────────────────────────
def render():
    _init()
    st.markdown(
        '<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">'
        '📊 Spread Chart</div>', unsafe_allow_html=True)

    # ── Mode selector ─────────────────────────────────────────────────────────
    mode_col, _, ref_col = st.columns([2, 2, 1])
    with mode_col:
        chart_mode = st.radio(
            "Chart Mode",
            ["📡 Live (real-time updates)", "📜 Historical (today's candles)"],
            horizontal=True, key="sp_mode",
            help="Live mode updates every second. Historical fetches today's full OHLCV.")
    with ref_col:
        if st.button("🔄 Refresh", use_container_width=True, key="sp_ref_btn"):
            _SS.sp_live_hist = []
            _SS.sp_df        = None
            _SS.sp_result    = None
            st.rerun()

    is_live = "Live" in chart_mode

    # ── Leg configuration ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown('<div class="sec-header">Legs</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        n = st.selectbox("Number of Legs", list(range(2, 7)),
                         index=_SS.sp_n_legs - 2, key="sp_legs_sel")
        _SS.sp_n_legs = n
    with c2:
        chart_type = st.selectbox("Chart Type", ["Line", "Candlestick"], key="sp_ct_sel")
        _SS.sp_chart_type = chart_type
    with c3:
        tf = st.selectbox("Timeframe", list(TF_MAP.keys()), key="sp_tf_sel")
        _SS.sp_tf = tf

    legs  = []
    leg_cols = st.columns(n)
    for i in range(n):
        with leg_cols[i]:
            st.markdown(
                f'<div style="font-size:10px;color:#787b86;margin-bottom:6px;background:#2a2e39;'
                f'padding:2px 8px;border-radius:10px;display:inline-block;">LEG {i+1}</div>',
                unsafe_allow_html=True)
            idx    = st.selectbox("Index", ["NIFTY","SENSEX","BANKNIFTY"],
                                  key=f"sp_idx_{i}", label_visibility="collapsed")
            exps, exp_err = _load_expiries(idx)
            if not exps:
                st.markdown(
                    f'<div style="font-size:11px;color:#ff9800;">⏳ {exp_err or "Loading…"}</div>',
                    unsafe_allow_html=True)
                if st.button("🔄", key=f"re_exp_{i}"):
                    _SS.pop(f"expiries_{idx}", None); st.rerun()
                legs.append(dict(index=idx, strike=0, expiry="", cp="CE",
                                 bs="Buy" if i%2==0 else "Sell", ratio=1, ltp=0.0, net=0.0))
                continue
            expiry = st.selectbox("Expiry", exps,
                                  key=f"sp_exp_{i}", label_visibility="collapsed")
            strikes, str_err = _load_strikes(idx, expiry)
            if not strikes:
                st.markdown(
                    f'<div style="font-size:11px;color:#ff9800;">⏳ {str_err or "Loading…"}</div>',
                    unsafe_allow_html=True)
                legs.append(dict(index=idx, strike=0, expiry=expiry, cp="CE",
                                 bs="Buy" if i%2==0 else "Sell", ratio=1, ltp=0.0, net=0.0))
                continue
            atm    = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx, strikes[len(strikes)//2])
            def_s  = min(strikes, key=lambda x: abs(x - atm))
            cur    = _SS.get(f"sp_strike_{i}")
            didx   = strikes.index(cur) if cur in strikes else strikes.index(def_s)
            strike = st.selectbox("Strike", strikes, index=didx,
                                  key=f"sp_strike_{i}", label_visibility="collapsed")
            cp     = st.selectbox("CE/PE", ["CE","PE"],
                                  key=f"sp_cp_{i}", label_visibility="collapsed")
            bs     = st.selectbox("Buy/Sell", ["Buy","Sell"],
                                  index=0 if i%2==0 else 1,
                                  key=f"sp_bs_{i}", label_visibility="collapsed")
            ratio  = st.number_input("Ratio", 1, 10, 1,
                                     key=f"sp_ratio_{i}", label_visibility="collapsed")
            # Show live LTP
            ltp = 0.0
            try:
                ltp = get_option_price(idx, strike, expiry, cp)
                sign   = 1 if bs == "Buy" else -1
                signed = round(ltp * ratio * sign, 2)
                clr    = "#26a69a" if signed >= 0 else "#ef5350"
                st.markdown(
                    f'<div style="font-size:11px;color:#787b86;margin-top:3px;">'
                    f'LTP: <span style="color:#d1d4dc;">{ltp:.2f}</span>'
                    f'&nbsp; Net: <span style="color:{clr};">{signed:+.2f}</span></div>',
                    unsafe_allow_html=True)
            except Exception:
                st.markdown('<div style="font-size:10px;color:#787b86;margin-top:3px;">LTP: —</div>',
                            unsafe_allow_html=True)
            legs.append(dict(index=idx, strike=strike, expiry=expiry,
                             cp=cp, bs=bs, ratio=ratio, ltp=ltp,
                             net=round((1 if bs=="Buy" else -1)*ltp*ratio, 2)))

    valid_legs = [l for l in legs if l["expiry"] and l["strike"] > 0]
    _SS.sp_legs_live = valid_legs
    st.markdown(
        f'<div style="font-size:10px;color:{"#26a69a" if len(valid_legs)==n else "#ff9800"};">'
        f'✓ {len(valid_legs)}/{n} legs configured</div>',
        unsafe_allow_html=True)

    if len(valid_legs) < 2:
        st.info("Configure at least 2 legs to see the chart.")
        return

    st.markdown("---")

    # ══════════════════════════════════════════════════════════════════════════
    # LIVE MODE — true real-time loop
    # ══════════════════════════════════════════════════════════════════════════
    if is_live:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">'
            '<div style="width:8px;height:8px;background:#26a69a;border-radius:50%;'
            'animation:pulse 1s infinite;"></div>'
            '<div style="font-size:12px;color:#26a69a;font-weight:600;">LIVE</div>'
            '<div style="font-size:11px;color:#787b86;">Updates every second · '
            'Price = sum of all leg LTPs · Click Stop to freeze</div></div>',
            unsafe_allow_html=True)

        # Live value display area
        val_placeholder  = st.empty()
        chart_placeholder = st.empty()
        status_placeholder = st.empty()

        col_start, col_stop, col_clear = st.columns(3)
        with col_start:
            start = st.button("▶ Start Live Feed", type="primary",
                               use_container_width=True, key="sp_live_start")
        with col_stop:
            stop = st.button("⏹ Stop", type="secondary",
                              use_container_width=True, key="sp_live_stop")
        with col_clear:
            if st.button("🗑 Clear History", use_container_width=True, key="sp_live_clear"):
                _SS.sp_live_hist = []
                st.rerun()

        if stop:
            _SS.sp_live_running = False

        if start:
            _SS.sp_live_running = True
            _SS.sp_live_hist    = []

        # Draw existing history even when stopped
        if _SS.sp_live_hist:
            fig = _build_chart(_SS.sp_live_hist, {"legs": valid_legs}, chart_type, tf)
            chart_placeholder.plotly_chart(
                fig, use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False,
                        "modeBarButtonsToRemove": ["lasso2d","select2d"]})
            last_val = _SS.sp_live_hist[-1][1]
            clr = "#26a69a" if last_val >= 0 else "#ef5350"
            val_placeholder.markdown(
                f'<div style="font-size:28px;font-weight:700;color:{clr};'
                f'padding:6px 0;">{last_val:+.2f}</div>',
                unsafe_allow_html=True)

        # ── LIVE LOOP — runs only while _SS.sp_live_running is True ──────────
        if _SS.sp_live_running:
            status_placeholder.markdown(
                '<div style="font-size:11px;color:#26a69a;">🔴 Fetching live data…</div>',
                unsafe_allow_html=True)
            tick_count = 0
            while _SS.sp_live_running:
                try:
                    val  = _live_spread_value(valid_legs)
                    now  = pd.Timestamp.now()
                    _SS.sp_live_hist.append((now, val))

                    # Keep max 3600 ticks (1 hour at 1s)
                    if len(_SS.sp_live_hist) > 3600:
                        _SS.sp_live_hist = _SS.sp_live_hist[-3600:]

                    # Update chart
                    fig = _build_chart(_SS.sp_live_hist, {"legs": valid_legs}, chart_type, tf)
                    chart_placeholder.plotly_chart(
                        fig, use_container_width=True,
                        config={"scrollZoom": True, "displaylogo": False,
                                "modeBarButtonsToRemove": ["lasso2d","select2d"]})

                    # Update value display
                    clr = "#26a69a" if val >= 0 else "#ef5350"
                    val_placeholder.markdown(
                        f'<div style="font-size:28px;font-weight:700;color:{clr};'
                        f'padding:6px 0;">{val:+.2f}</div>',
                        unsafe_allow_html=True)

                    tick_count += 1
                    status_placeholder.markdown(
                        f'<div style="font-size:10px;color:#787b86;">'
                        f'🟢 Tick #{tick_count} · {now.strftime("%H:%M:%S")} · '
                        f'{len(_SS.sp_live_hist)} data points</div>',
                        unsafe_allow_html=True)

                except Exception as e:
                    status_placeholder.markdown(
                        f'<div style="font-size:10px;color:#ef5350;">⚠ {e}</div>',
                        unsafe_allow_html=True)

                time.sleep(1)   # 1-second tick — same as TradingView live feed

        # ── Greeks (live) ─────────────────────────────────────────────────────
        show_greeks = st.checkbox("Show Net Greeks", value=False, key="sp_show_greeks_live")
        if show_greeks and valid_legs and any(l["ltp"] > 0 for l in valid_legs):
            try:
                g = calc_greeks_for_legs(valid_legs)
                for col, (lbl, val, clr) in zip(st.columns(5), [
                    ("Net Δ",   f"{g['delta']:+.4f}",  "#2962ff"),
                    ("Net Γ",   f"{g['gamma']:+.6f}",  "#ff9800"),
                    ("Net V",   f"{g['vega']:+.4f}",   "#9c27b0"),
                    ("Net θ",   f"{g['theta']:+.4f}",  "#ef5350"),
                    ("Net IV",  f"{g['net_iv']:.2f}%", "#26a69a"),
                ]):
                    with col:
                        st.markdown(
                            f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                            f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                            unsafe_allow_html=True)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # HISTORICAL MODE — fetch today's OHLCV candles from Fyers
    # ══════════════════════════════════════════════════════════════════════════
    else:
        show_greeks = st.checkbox("Show Net Greeks", value=False, key="sp_show_greeks_hist")

        # Show last chart if available
        if _SS.sp_df is not None and _SS.sp_result is not None:
            st.plotly_chart(
                _build_candle_chart(_SS.sp_df, _SS.sp_result, chart_type, tf),
                use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False,
                        "modeBarButtonsToRemove": ["autoScale2d","lasso2d","select2d"]})
            r  = _SS.sp_result
            sv = r["spread"]
            for col, (lbl, val, clr) in zip(st.columns(5), [
                ("SPREAD",     f"{sv:+.2f}",           "#26a69a" if sv >= 0 else "#ef5350"),
                ("NET PREM",   f"{r['net_prem']:+.2f}", "#d1d4dc"),
                ("MAX PROFIT", "Unlimited" if r["max_profit"] is None
                               else f"{r['max_profit']:.2f}", "#26a69a"),
                ("MAX LOSS",   f"{r['max_loss']:.2f}" if r["max_loss"] else "—", "#ef5350"),
                ("BREAKEVEN",  f"{r['be']:.0f}" if r["be"] else "—", "#d1d4dc"),
            ]):
                with col:
                    st.markdown(
                        f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                        f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="height:160px;display:flex;align-items:center;justify-content:center;'
                'background:#1e222d;border:1px solid #2a2e39;border-radius:8px;margin-bottom:12px;">'
                '<div style="font-size:13px;color:#787b86;">Click Calculate & Plot below</div></div>',
                unsafe_allow_html=True)

        if st.button("⚡ Calculate & Plot", use_container_width=True,
                     type="primary", key="sp_calc_hist"):
            with st.spinner("Fetching live prices & candles…"):
                fresh_legs = []; ok = True
                for leg in valid_legs:
                    try:
                        ltp  = get_option_price(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
                        sign = 1 if leg["bs"] == "Buy" else -1
                        fresh_legs.append({**leg, "ltp": ltp,
                                           "net": round(sign * ltp * leg["ratio"], 2)})
                    except Exception as e:
                        st.error(f"LTP fetch Leg {valid_legs.index(leg)+1}: {e}")
                        ok = False; break
            if ok:
                buys  = [l for l in fresh_legs if l["bs"] == "Buy"]
                sells = [l for l in fresh_legs if l["bs"] == "Sell"]
                spread   = (sum(l["ltp"]*l["ratio"] for l in buys)
                            - sum(l["ltp"]*l["ratio"] for l in sells))
                net_prem = sum(l["net"] for l in fresh_legs)
                max_profit = max_loss = be = None
                if buys and sells:
                    sd = abs(buys[0]["strike"] - sells[0]["strike"])
                    max_profit = sd - abs(spread) if sd > abs(spread) else None
                    max_loss   = abs(spread)
                    be         = (buys[0]["strike"] + spread if buys[0]["cp"] == "CE"
                                  else buys[0]["strike"] - spread)
                with st.spinner("Fetching candle history…"):
                    try:
                        tf_min    = TF_MAP[tf]
                        _SS.sp_df = generate_spread_ohlcv(fresh_legs, tf_minutes=tf_min)
                        _SS.sp_result = dict(
                            spread=round(spread, 2), net_prem=round(net_prem, 2),
                            max_profit=max_profit, max_loss=max_loss, be=be,
                            legs=fresh_legs)
                        st.rerun()
                    except Exception as e:
                        st.error(
                            f"Candle fetch failed: {e}\n\n"
                            "Tip: Candle history is only available during market hours "
                            "(9:15 AM – 3:30 PM IST). Use **Live mode** outside these hours.")

        if (show_greeks and valid_legs
                and any(l["ltp"] > 0 for l in valid_legs)):
            st.markdown('<div class="sec-header" style="margin-top:12px;">Net Greeks</div>',
                        unsafe_allow_html=True)
            try:
                g = calc_greeks_for_legs(valid_legs)
                hi_avg = lo_avg = None
                if _SS.sp_df is not None:
                    closes = _SS.sp_df["close"].dropna()
                    if len(closes) >= 5:
                        hi_avg = round(closes.nlargest(5).mean(), 2)
                        lo_avg = round(closes.nsmallest(5).mean(), 2)
                for col, (lbl, val, clr) in zip(st.columns(7), [
                    ("NET Δ",    f"{g['delta']:+.4f}",  "#2962ff"),
                    ("NET Γ",    f"{g['gamma']:+.6f}",  "#ff9800"),
                    ("NET V",    f"{g['vega']:+.4f}",   "#9c27b0"),
                    ("NET θ",    f"{g['theta']:+.4f}",  "#ef5350"),
                    ("NET IV",   f"{g['net_iv']:.2f}%", "#26a69a"),
                    ("AVG HIGH", f"{hi_avg:.2f}" if hi_avg else "—", "#26a69a"),
                    ("AVG LOW",  f"{lo_avg:.2f}" if lo_avg else "—", "#ef5350"),
                ]):
                    with col:
                        st.markdown(
                            f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                            f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                            unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Greeks: {e}")

        if _SS.sp_result:
            st.markdown("---")
            df_show = pd.DataFrame(_SS.sp_result["legs"])[
                ["index","strike","expiry","cp","bs","ratio","ltp","net"]]
            df_show.columns = ["Index","Strike","Expiry","C/P","B/S","Ratio","LTP","Net"]
            st.dataframe(df_show, use_container_width=True, hide_index=True)

    # ── Safety Calculator ─────────────────────────────────────────────────────
    if valid_legs:
        _render_safety(valid_legs)
