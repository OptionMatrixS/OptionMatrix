"""
spread_chart.py — Spread Chart + Safety Calculator
Live mode: st.rerun() pattern — each Streamlit rerun = one price tick.
Historical mode: today's OHLCV candles from Fyers.
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

REFRESH_INTERVAL = 3   # seconds between live ticks

# ─────────────────────────────────────────────────────────────────────────────
def _init():
    for k, v in [
        ("sp_n_legs", 2), ("sp_chart_type", "Line"),
        ("sp_tf", "1m"), ("sp_result", None), ("sp_df", None),
        ("sp_legs_live", []), ("sp_live_hist", []),
        ("sp_live_on", False), ("sp_last_tick", 0.0),
    ]:
        if k not in _SS:
            _SS[k] = v

# ─── loaders ──────────────────────────────────────────────────────────────────
def _load_expiries(index):
    ck = f"expiries_{index}"
    if _SS.get(ck): return list(_SS[ck].keys()), None
    try:    return get_index_expiries(index), None
    except Exception as e: return [], str(e)

def _load_strikes(index, expiry):
    if not expiry: return [], "no expiry"
    ck = f"strikes_{index}_{expiry}"
    if _SS.get(ck): return _SS[ck], None
    try:    return get_index_strikes(index, expiry), None
    except Exception as e: return [], str(e)

# ─── spread value ─────────────────────────────────────────────────────────────
def _spread_now(legs) -> float:
    total = 0.0
    for leg in legs:
        try:
            ltp   = get_live_ltp(leg["index"], leg["strike"], leg["expiry"], leg["cp"])
            sign  = 1 if leg["bs"] == "Buy" else -1
            total += sign * ltp * leg["ratio"]
        except Exception:
            pass
    return round(total, 2)

# ─── live chart ───────────────────────────────────────────────────────────────
def _live_fig(hist: list, legs: list, chart_type: str):
    if not hist:
        return go.Figure()

    times  = [h[0] for h in hist]
    values = [h[1] for h in hist]
    last   = values[-1]
    first  = values[0]

    up_clr = "#26a69a"
    dn_clr = "#ef5350"
    line_c = up_clr if last >= first else dn_clr
    fill_c = "rgba(38,166,154,0.08)" if last >= first else "rgba(239,83,80,0.08)"

    fig = go.Figure()

    if chart_type == "Candlestick" and len(hist) >= 2:
        df = (pd.DataFrame({"t": times, "v": values})
              .set_index("t").resample("1min")["v"]
              .ohlc().dropna().reset_index())
        if not df.empty:
            fig.add_trace(go.Candlestick(
                x=df["t"], open=df["open"], high=df["high"],
                low=df["low"], close=df["close"],
                increasing_line_color=up_clr, increasing_fillcolor=up_clr,
                decreasing_line_color=dn_clr, decreasing_fillcolor=dn_clr,
                line=dict(width=1), whiskerwidth=0.3, name="Spread"))
            last = float(df["close"].iloc[-1])
        else:
            # Not enough data yet for candlestick — fall back to line
            fig.add_trace(go.Scatter(
                x=times, y=values, mode="lines",
                line=dict(color=line_c, width=2),
                fill="tozeroy", fillcolor=fill_c, name="Spread"))
    else:
        fig.add_trace(go.Scatter(
            x=times, y=values, mode="lines",
            line=dict(color=line_c, width=2),
            fill="tozeroy", fillcolor=fill_c, name="Spread",
            hovertemplate="%{x|%H:%M:%S}<br>%{y:+.2f}<extra></extra>"))

    fig.add_hline(y=0, line=dict(color="#363a45", width=1, dash="dot"))

    title_parts = " / ".join(
        f"{l['index']} {l['strike']}{l['cp']} {l['bs'][0]}" for l in legs[:4])
    fig.add_annotation(
        x=times[-1], y=last,
        text=f"  {last:+.2f}",
        showarrow=False,
        font=dict(size=12, color="#fff", family="JetBrains Mono"),
        bgcolor=up_clr if last >= 0 else dn_clr,
        borderpad=4, xanchor="left")

    fig.update_layout(
        title=dict(text=title_parts, font=dict(size=11, color="#d1d4dc"), x=0),
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        xaxis=dict(
            gridcolor="#1e222d", tickfont=dict(size=9, color="#787b86"),
            rangeslider=dict(visible=False),
            showline=False, zeroline=False, fixedrange=False,
            tickformat="%H:%M:%S"),
        yaxis=dict(
            gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
            showline=False, zeroline=False, side="right", fixedrange=False),
        margin=dict(l=10, r=72, t=36, b=28),
        height=420,
        hovermode="x unified", dragmode="pan",
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                        font=dict(size=11, color="#d1d4dc")))
    return fig

# ─── historical candle chart ──────────────────────────────────────────────────
def _hist_fig(df: pd.DataFrame, result: dict, chart_type: str, tf: str):
    lgs = result.get("legs", [])
    title = " / ".join(
        f"{l['index']} {l['strike']}{l['cp']} {l['bs'][0]}" for l in lgs[:4])
    title += f"  [{tf}]"

    fig  = go.Figure()
    last = float(df["close"].iloc[-1])

    if chart_type == "Candlestick":
        fig.add_trace(go.Candlestick(
            x=df["time"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="Spread",
            increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
            decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
            line=dict(width=1), whiskerwidth=0.3))
    else:
        clr = "#26a69a" if last >= 0 else "#ef5350"
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["close"], mode="lines",
            line=dict(color=clr, width=1.8),
            fill="tozeroy",
            fillcolor=f"rgba({'38,166,154' if last>=0 else '239,83,80'},0.07)",
            name="Spread"))

    fig.add_hline(y=0, line=dict(color="#363a45", width=1, dash="dot"))
    fig.add_annotation(
        x=df["time"].iloc[-1], y=last,
        text=f"  {last:+.2f}",
        showarrow=False, font=dict(size=11, color="#fff"),
        bgcolor="#26a69a" if last >= 0 else "#ef5350",
        borderpad=4, xanchor="left")

    fig.update_layout(
        title=dict(text=title, font=dict(size=11, color="#d1d4dc"), x=0),
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        xaxis=dict(gridcolor="#1e222d", tickfont=dict(size=9, color="#787b86"),
                   rangeslider=dict(visible=False),
                   showline=False, zeroline=False, tickformat="%H:%M"),
        yaxis=dict(gridcolor="#1e222d", tickfont=dict(size=10, color="#787b86"),
                   showline=False, zeroline=False, side="right"),
        margin=dict(l=10, r=72, t=36, b=28), height=420,
        hovermode="x unified", dragmode="pan",
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                        font=dict(size=11, color="#d1d4dc")))
    return fig

# ─── safety calculator ────────────────────────────────────────────────────────
def _nearest(strikes, target):
    if not strikes: return target
    return min(strikes, key=lambda x: abs(x - target))

def _render_safety(legs):
    st.markdown("---")
    st.markdown(
        '<div style="font-size:16px;font-weight:600;color:#d1d4dc;margin-bottom:4px;">'
        '🛡️ Safety Calculator'
        '<span style="font-size:11px;color:#787b86;margin-left:10px;'
        'padding:2px 8px;background:#1e222d;border:1px solid #2a2e39;border-radius:8px;">'
        'Auto-linked to legs above</span></div>',
        unsafe_allow_html=True)

    n_legs = len(legs)
    sc_col, tbl_col = st.columns([1, 3], gap="medium")

    with sc_col:
        diffs = []
        for i, leg in enumerate(legs):
            d_def = 100 if leg["index"] in ("NIFTY","BANKNIFTY") else 500
            d = st.number_input(
                f"LEG {i+1} ({leg['index']}) step",
                min_value=1, max_value=10000,
                value=int(_SS.get(f"sc_diff_{i}", d_def)),
                step=d_def, key=f"sc_diff_{i}")
            diffs.append(int(d))
        n_rows = int(st.number_input("Rows ±", 1, 10, 3, key="sc_n_rows"))
        build  = st.button("🛡️ Build", use_container_width=True,
                            type="primary", key="sc_build")

    with tbl_col:
        sig = str([(l["index"],l["strike"],l["expiry"],l["cp"]) for l in legs]) \
              + str(diffs) + str(n_rows)
        if build or _SS.get("sc_sig") != sig:
            _SS.sc_sig = sig
            mat = []
            for off in range(-n_rows, n_rows + 1):
                row = {"SERIES": f"{off:+d}" if off != 0 else "0 (BASE)"}
                stk_row = []
                for i, leg in enumerate(legs):
                    avail  = _SS.get(f"strikes_{leg['index']}_{leg['expiry']}", [])
                    tgt    = leg["strike"] + off * diffs[i]
                    near   = _nearest(avail, tgt) if avail else tgt
                    row[f"LEG {i+1}"] = near
                    stk_row.append(near)
                bid_t = ask_t = ltp_t = 0.0
                for i, leg in enumerate(legs):
                    try:
                        q    = get_live_quote(leg["index"], stk_row[i], leg["expiry"], leg["cp"])
                        sign = 1 if leg["bs"] == "Buy" else -1
                        bid_t += sign * q["bid"]  * leg["ratio"]
                        ask_t += sign * q["ask"]  * leg["ratio"]
                        ltp_t += sign * q["ltp"]  * leg["ratio"]
                    except Exception:
                        pass
                row.update({"BID": round(bid_t,2), "ASK": round(ask_t,2), "LTP": round(ltp_t,2)})
                mat.append((off, row))
            _SS.sc_matrix = mat

        mat = _SS.get("sc_matrix", [])
        if not mat:
            st.info("Click Build to generate the safety matrix.")
            return

        hdr = ["SERIES"] + [f"LEG {i+1}" for i in range(n_legs)] + ["BID","ASK","LTP"]
        # Interval info row
        ivl = {"SERIES":"STEP"}
        for i in range(n_legs): ivl[f"LEG {i+1}"] = diffs[i]
        ivl.update({"BID":"—","ASK":"—","LTP":"—"})

        th = "".join(f'<th style="padding:5px 8px;font-size:10px;color:#787b86;'
                     f'text-align:center;border-bottom:1px solid #2a2e39;">{c}</th>'
                     for c in hdr)
        ir = "".join(f'<td style="padding:5px 8px;font-size:11px;font-weight:700;'
                     f'color:#ff9800;text-align:center;background:#1a1f2e;">{ivl.get(c,"")}</td>'
                     for c in hdr)
        body = ""
        for off, row in mat:
            base = (off == 0)
            bg   = "#162040" if base else "#1e222d"
            bl   = "border-left:3px solid #2962ff;" if base else "border-left:3px solid transparent;"
            cells = ""
            for c in hdr:
                v = row.get(c,"")
                if c == "SERIES":
                    fw = "700" if base else "400"
                    cc = "#2962ff" if base else "#787b86"
                    cells += (f'<td style="padding:5px 8px;font-size:11px;font-weight:{fw};'
                               f'color:{cc};text-align:center;">{v}</td>')
                elif c.startswith("LEG"):
                    fw = "600" if base else "400"
                    cc = "#fff" if base else "#d1d4dc"
                    cells += (f'<td style="padding:5px 8px;font-size:12px;font-weight:{fw};'
                               f'color:{cc};font-family:monospace;text-align:center;">{v}</td>')
                else:
                    try:
                        fv = float(v)
                        cc = "#26a69a" if fv >= 0 else "#ef5350"
                        fw = "600" if base else "400"
                        txt= f"{fv:+.2f}"
                    except Exception:
                        cc = "#787b86"; fw = "400"; txt = str(v)
                    cells += (f'<td style="padding:5px 8px;font-size:12px;font-weight:{fw};'
                               f'color:{cc};font-family:monospace;text-align:center;">{txt}</td>')
            body += f'<tr style="background:{bg};{bl}border-bottom:1px solid #2a2e39;">{cells}</tr>'

        st.markdown(
            f'<div style="overflow-x:auto;border:1px solid #2a2e39;border-radius:8px;">'
            f'<table style="width:100%;border-collapse:collapse;">'
            f'<thead><tr style="background:#1a1f2e;">{ir}</tr>'
            f'<tr style="background:#1a1f2e;">{th}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>',
            unsafe_allow_html=True)

        if st.button("📥 Export Safety Matrix", key="sc_export"):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                pd.DataFrame([r for _,r in mat]).to_excel(w, index=False, sheet_name="Safety")
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

    # ── Leg configuration ─────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    with c1:
        n = st.selectbox("Legs", list(range(2, 7)),
                         index=_SS.sp_n_legs - 2, key="sp_legs_sel")
        _SS.sp_n_legs = n
    with c2:
        chart_type = st.selectbox("Chart Type", ["Line","Candlestick"], key="sp_ct_sel")
        _SS.sp_chart_type = chart_type
    with c3:
        tf = st.selectbox("Timeframe", list(TF_MAP.keys()), key="sp_tf_sel")
        _SS.sp_tf = tf

    legs     = []
    leg_cols = st.columns(n)
    for i in range(n):
        with leg_cols[i]:
            st.markdown(
                f'<div style="font-size:10px;color:#787b86;margin-bottom:6px;'
                f'background:#2a2e39;padding:2px 8px;border-radius:10px;'
                f'display:inline-block;">LEG {i+1}</div>',
                unsafe_allow_html=True)
            idx = st.selectbox("Index", ["NIFTY","SENSEX","BANKNIFTY"],
                               key=f"sp_idx_{i}", label_visibility="collapsed")
            exps, exp_err = _load_expiries(idx)
            if not exps:
                st.markdown(f'<div style="font-size:11px;color:#ff9800;">'
                            f'⏳ {exp_err or "loading…"}</div>', unsafe_allow_html=True)
                if st.button("🔄", key=f"re_exp_{i}"):
                    _SS.pop(f"expiries_{idx}", None); st.rerun()
                legs.append(dict(index=idx, strike=0, expiry="", cp="CE",
                                 bs="Buy" if i%2==0 else "Sell", ratio=1, ltp=0., net=0.))
                continue
            expiry = st.selectbox("Expiry", exps, key=f"sp_exp_{i}",
                                  label_visibility="collapsed")
            strikes, _ = _load_strikes(idx, expiry)
            if not strikes:
                st.markdown('<div style="font-size:11px;color:#ff9800;">⏳ loading strikes…</div>',
                            unsafe_allow_html=True)
                legs.append(dict(index=idx, strike=0, expiry=expiry, cp="CE",
                                 bs="Buy" if i%2==0 else "Sell", ratio=1, ltp=0., net=0.))
                continue
            atm   = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx, strikes[len(strikes)//2])
            def_s = min(strikes, key=lambda x: abs(x - atm))
            cur   = _SS.get(f"sp_strike_{i}")
            didx  = strikes.index(cur) if cur in strikes else strikes.index(def_s)
            strike= st.selectbox("Strike", strikes, index=didx,
                                 key=f"sp_strike_{i}", label_visibility="collapsed")
            cp    = st.selectbox("CE/PE", ["CE","PE"], key=f"sp_cp_{i}",
                                 label_visibility="collapsed")
            bs    = st.selectbox("Buy/Sell", ["Buy","Sell"],
                                 index=0 if i%2==0 else 1,
                                 key=f"sp_bs_{i}", label_visibility="collapsed")
            ratio = st.number_input("Ratio", 1, 10, 1,
                                    key=f"sp_ratio_{i}", label_visibility="collapsed")
            ltp = 0.
            try:
                ltp    = get_option_price(idx, strike, expiry, cp)
                signed = round((1 if bs=="Buy" else -1) * ltp * ratio, 2)
                clr    = "#26a69a" if signed >= 0 else "#ef5350"
                st.markdown(
                    f'<div style="font-size:11px;color:#787b86;margin-top:3px;">'
                    f'LTP: <span style="color:#d1d4dc;">{ltp:.2f}</span>'
                    f'&nbsp;Net: <span style="color:{clr};">{signed:+.2f}</span></div>',
                    unsafe_allow_html=True)
            except Exception:
                st.markdown('<div style="font-size:10px;color:#787b86;margin-top:3px;">LTP: —</div>',
                            unsafe_allow_html=True)
            legs.append(dict(index=idx, strike=strike, expiry=expiry,
                             cp=cp, bs=bs, ratio=ratio, ltp=ltp,
                             net=round((1 if bs=="Buy" else -1)*ltp*ratio, 2)))

    valid_legs = [l for l in legs if l["expiry"] and l["strike"] > 0]
    _SS.sp_legs_live = valid_legs
    n_ready = len(valid_legs)
    st.markdown(
        f'<div style="font-size:10px;color:{"#26a69a" if n_ready==n else "#ff9800"};">'
        f'✓ {n_ready}/{n} legs ready</div>', unsafe_allow_html=True)

    if n_ready < 2:
        st.info("Configure at least 2 legs above.")
        if valid_legs: _render_safety(valid_legs)
        return

    st.markdown("---")

    # ── Chart mode tabs ───────────────────────────────────────────────────────
    tab_live, tab_hist = st.tabs(["📡 Live Feed", "📜 Historical Candles"])

    # ═════════════════════════════════════════════════════════════════════════
    # LIVE FEED TAB
    # Uses st.rerun() pattern: each rerun = one price tick.
    # The Stop button works because each rerun re-renders the buttons.
    # time.sleep(REFRESH_INTERVAL) is called ONCE at the end before st.rerun().
    # ═════════════════════════════════════════════════════════════════════════
    with tab_live:
        st.markdown(
            '<div style="font-size:11px;color:#787b86;margin-bottom:8px;">'
            f'Updates every <b style="color:#d1d4dc;">{REFRESH_INTERVAL}s</b> · '
            'Uses live Fyers quotes · Works 24/7</div>',
            unsafe_allow_html=True)

        # Controls
        btn_c1, btn_c2, btn_c3 = st.columns(3)
        with btn_c1:
            if st.button("▶ Start Live Feed", type="primary",
                         use_container_width=True, key="sp_start"):
                _SS.sp_live_on   = True
                _SS.sp_live_hist = []
                _SS.sp_last_tick = 0.0
                st.rerun()
        with btn_c2:
            if st.button("⏹ Stop", type="secondary",
                         use_container_width=True, key="sp_stop"):
                _SS.sp_live_on = False
                st.rerun()
        with btn_c3:
            if st.button("🗑 Clear", use_container_width=True, key="sp_clear"):
                _SS.sp_live_hist = []
                _SS.sp_last_tick = 0.0
                st.rerun()

        # Status badge
        if _SS.sp_live_on:
            n_ticks = len(_SS.sp_live_hist)
            last_t  = _SS.sp_live_hist[-1][0].strftime("%H:%M:%S") if _SS.sp_live_hist else "—"
            st.markdown(
                f'<div style="display:inline-flex;align-items:center;gap:6px;'
                f'padding:4px 10px;background:#0d2b1f;border:1px solid #26a69a40;'
                f'border-radius:20px;font-size:11px;color:#26a69a;">'
                f'🟢 LIVE &nbsp;|&nbsp; {n_ticks} ticks &nbsp;|&nbsp; last: {last_t}</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="display:inline-flex;align-items:center;gap:6px;'
                'padding:4px 10px;background:#1e222d;border:1px solid #2a2e3980;'
                'border-radius:20px;font-size:11px;color:#787b86;">'
                '⏹ STOPPED — click Start to begin</div>',
                unsafe_allow_html=True)

        # Chart area
        if _SS.sp_live_hist:
            last_val = _SS.sp_live_hist[-1][1]
            clr = "#26a69a" if last_val >= 0 else "#ef5350"
            st.markdown(
                f'<div style="font-size:32px;font-weight:700;'
                f'color:{clr};padding:4px 0;font-family:monospace;">'
                f'{last_val:+.2f}</div>',
                unsafe_allow_html=True)
            fig = _live_fig(_SS.sp_live_hist, valid_legs, chart_type)
            st.plotly_chart(fig, use_container_width=True,
                            config={"scrollZoom": True, "displaylogo": False,
                                    "modeBarButtonsToRemove": ["lasso2d","select2d"]})
        else:
            st.markdown(
                '<div style="height:200px;display:flex;align-items:center;'
                'justify-content:center;background:#1e222d;border:1px solid #2a2e39;'
                'border-radius:8px;"><div style="text-align:center;color:#787b86;">'
                '<div style="font-size:24px;margin-bottom:8px;">📡</div>'
                'Click ▶ Start Live Feed</div></div>',
                unsafe_allow_html=True)

        # ── THE KEY: sleep then rerun — this is the correct Streamlit pattern ──
        # Each rerun = one tick. Stop button works because it sets sp_live_on=False
        # before the sleep. On next rerun sp_live_on is False so we don't sleep/rerun.
        if _SS.sp_live_on:
            now = time.time()
            elapsed = now - _SS.sp_last_tick
            if elapsed >= REFRESH_INTERVAL:
                # Fetch price
                try:
                    val = _spread_now(valid_legs)
                    _SS.sp_live_hist.append((pd.Timestamp.now(), val))
                    if len(_SS.sp_live_hist) > 7200:   # max 2h at 1s
                        _SS.sp_live_hist = _SS.sp_live_hist[-7200:]
                    _SS.sp_last_tick = now
                except Exception as e:
                    st.error(f"Price fetch error: {e}")
            wait = max(0.1, REFRESH_INTERVAL - (time.time() - _SS.sp_last_tick))
            time.sleep(wait)
            st.rerun()

        # Greeks
        show_g = st.checkbox("Show Net Greeks", value=False, key="sp_greeks_live")
        if show_g and any(l["ltp"] > 0 for l in valid_legs):
            try:
                g = calc_greeks_for_legs(valid_legs)
                for col, (lbl, val, clr) in zip(st.columns(5), [
                    ("Net Δ",  f"{g['delta']:+.4f}",  "#2962ff"),
                    ("Net Γ",  f"{g['gamma']:+.6f}",  "#ff9800"),
                    ("Net V",  f"{g['vega']:+.4f}",   "#9c27b0"),
                    ("Net θ",  f"{g['theta']:+.4f}",  "#ef5350"),
                    ("Net IV", f"{g['net_iv']:.2f}%", "#26a69a"),
                ]):
                    with col:
                        st.markdown(
                            f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                            f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                            unsafe_allow_html=True)
            except Exception:
                pass

    # ═════════════════════════════════════════════════════════════════════════
    # HISTORICAL CANDLES TAB
    # ═════════════════════════════════════════════════════════════════════════
    with tab_hist:
        st.markdown(
            '<div style="font-size:11px;color:#787b86;margin-bottom:8px;">'
            'Fetches today\'s OHLCV candles from Fyers. '
            'Available during market hours (9:15 AM – 3:30 PM IST).</div>',
            unsafe_allow_html=True)

        if _SS.sp_df is not None and _SS.sp_result is not None:
            r  = _SS.sp_result
            sv = r["spread"]
            for col, (lbl, val, clr) in zip(st.columns(5), [
                ("SPREAD",  f"{sv:+.2f}",           "#26a69a" if sv>=0 else "#ef5350"),
                ("NET PREM",f"{r['net_prem']:+.2f}", "#d1d4dc"),
                ("MAX P",   "∞" if r["max_profit"] is None
                            else f"{r['max_profit']:.2f}", "#26a69a"),
                ("MAX L",   f"{r['max_loss']:.2f}" if r["max_loss"] else "—", "#ef5350"),
                ("BE",      f"{r['be']:.0f}" if r["be"] else "—", "#d1d4dc"),
            ]):
                with col:
                    st.markdown(
                        f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                        f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                        unsafe_allow_html=True)
            st.plotly_chart(
                _hist_fig(_SS.sp_df, r, chart_type, tf),
                use_container_width=True,
                config={"scrollZoom": True, "displaylogo": False})
            df_show = pd.DataFrame(r["legs"])[
                ["index","strike","expiry","cp","bs","ratio","ltp","net"]]
            df_show.columns = ["Index","Strike","Expiry","C/P","B/S","Ratio","LTP","Net"]
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        else:
            st.markdown(
                '<div style="height:160px;display:flex;align-items:center;'
                'justify-content:center;background:#1e222d;border:1px solid #2a2e39;'
                'border-radius:8px;margin-bottom:10px;">'
                '<div style="font-size:13px;color:#787b86;">'
                'Click Calculate & Plot below</div></div>',
                unsafe_allow_html=True)

        show_g2 = st.checkbox("Show Net Greeks", value=False, key="sp_greeks_hist")
        if st.button("⚡ Calculate & Plot", type="primary",
                     use_container_width=False, key="sp_calc"):
            with st.spinner("Fetching prices…"):
                fresh = []; ok = True
                for leg in valid_legs:
                    try:
                        ltp  = get_option_price(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
                        sign = 1 if leg["bs"]=="Buy" else -1
                        fresh.append({**leg,"ltp":ltp,"net":round(sign*ltp*leg["ratio"],2)})
                    except Exception as e:
                        st.error(f"Leg {valid_legs.index(leg)+1} price error: {e}")
                        ok = False; break
            if ok:
                buys  = [l for l in fresh if l["bs"]=="Buy"]
                sells = [l for l in fresh if l["bs"]=="Sell"]
                spread   = (sum(l["ltp"]*l["ratio"] for l in buys)
                            - sum(l["ltp"]*l["ratio"] for l in sells))
                net_prem = sum(l["net"] for l in fresh)
                max_p = max_l = be = None
                if buys and sells:
                    sd    = abs(buys[0]["strike"] - sells[0]["strike"])
                    max_p = sd - abs(spread) if sd > abs(spread) else None
                    max_l = abs(spread)
                    be    = (buys[0]["strike"]+spread if buys[0]["cp"]=="CE"
                             else buys[0]["strike"]-spread)
                with st.spinner("Fetching candle history…"):
                    try:
                        tf_min    = TF_MAP[tf]
                        _SS.sp_df = generate_spread_ohlcv(fresh, tf_minutes=tf_min)
                        _SS.sp_result = dict(spread=round(spread,2), net_prem=round(net_prem,2),
                                             max_profit=max_p, max_loss=max_l, be=be, legs=fresh)
                        st.rerun()
                    except Exception as e:
                        st.error(
                            f"Candle history failed: {e}\n\n"
                            "Use the 📡 Live Feed tab — it works 24/7.")

        if show_g2 and any(l["ltp"]>0 for l in valid_legs):
            try:
                g = calc_greeks_for_legs(valid_legs)
                hi_avg = lo_avg = None
                if _SS.sp_df is not None:
                    c = _SS.sp_df["close"].dropna()
                    if len(c) >= 5:
                        hi_avg = round(c.nlargest(5).mean(), 2)
                        lo_avg = round(c.nsmallest(5).mean(), 2)
                for col, (lbl, val, clr) in zip(st.columns(7), [
                    ("Net Δ",   f"{g['delta']:+.4f}",  "#2962ff"),
                    ("Net Γ",   f"{g['gamma']:+.6f}",  "#ff9800"),
                    ("Net V",   f"{g['vega']:+.4f}",   "#9c27b0"),
                    ("Net θ",   f"{g['theta']:+.4f}",  "#ef5350"),
                    ("Net IV",  f"{g['net_iv']:.2f}%", "#26a69a"),
                    ("Avg Hi",  f"{hi_avg:.2f}" if hi_avg else "—", "#26a69a"),
                    ("Avg Lo",  f"{lo_avg:.2f}" if lo_avg else "—", "#ef5350"),
                ]):
                    with col:
                        st.markdown(
                            f'<div class="stat-chip"><div class="sc-label">{lbl}</div>'
                            f'<div class="sc-val" style="color:{clr};">{val}</div></div>',
                            unsafe_allow_html=True)
            except Exception:
                pass

    # ── Safety Calculator ─────────────────────────────────────────────────────
    _render_safety(valid_legs)
