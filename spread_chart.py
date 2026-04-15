import sys, os
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from data_helpers import (
    get_index_expiries, get_index_strikes,
    get_option_price, generate_spread_ohlcv,
    calc_greeks_for_legs, TF_MAP,
)

_SS = st.session_state

def _init():
    for k, v in [("sp_n_legs",2),("sp_chart_type","Candlestick"),
                 ("sp_tf","1m"),("sp_result",None),("sp_df",None),("sp_legs_live",[])]:
        if k not in _SS: _SS[k] = v

def _load_expiries(index):
    cache_key = f"expiries_{index}"
    if _SS.get(cache_key): return list(_SS[cache_key].keys()), None
    try:
        exps = get_index_expiries(index)
        return exps, None
    except Exception as e:
        return [], str(e)

def _load_strikes(index, expiry):
    if not expiry: return [], "No expiry selected."
    cache_key = f"strikes_{index}_{expiry}"
    if _SS.get(cache_key): return _SS[cache_key], None
    try:
        strikes = get_index_strikes(index, expiry)
        return strikes, None
    except Exception as e:
        return [], str(e)

def _validate_legs_ui(legs):
    errors = []
    for i, leg in enumerate(legs):
        n = i + 1
        if not leg.get("expiry"): errors.append(f"Leg {n}: Expiry not selected.")
        if not leg.get("strike") or leg["strike"] <= 0: errors.append(f"Leg {n}: Strike not selected.")
    return errors

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
        showarrow=False, font=dict(size=11, color="#fff", family="JetBrains Mono"),
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
        hoverlabel=dict(bgcolor="#1e222d", bordercolor="#2a2e39",
                        font=dict(size=11, color="#d1d4dc")))
    return fig

def render():
    _init()
    st.markdown('<div style="font-size:20px;font-weight:600;color:#d1d4dc;margin-bottom:8px;">📊 Spread Chart</div>',
                unsafe_allow_html=True)

    # ── Chart ────────────────────────────────────────────────────────────────
    if _SS.sp_df is not None:
        st.plotly_chart(_build_chart(_SS.sp_df, _SS.sp_result, _SS.sp_chart_type, _SS.sp_tf),
                        use_container_width=True, config={
                            "displayModeBar":True,"displaylogo":False,"scrollZoom":True,
                            "modeBarButtonsToRemove":["autoScale2d","lasso2d","select2d"]})
        if _SS.sp_result:
            r = _SS.sp_result; sv = r["spread"]
            items = [
                ("SPREAD",f"{sv:+.2f}","#26a69a" if sv>=0 else "#ef5350"),
                ("NET PREM",f"{r['net_prem']:+.2f}","#d1d4dc"),
                ("MAX PROFIT","Unlimited" if r['max_profit'] is None else f"{r['max_profit']:.2f}","#26a69a"),
                ("MAX LOSS",f"{r['max_loss']:.2f}" if r['max_loss'] else "—","#ef5350"),
                ("BREAKEVEN",f"{r['be']:.0f}" if r['be'] else "—","#d1d4dc"),
            ]
            for col,(label,val,color) in zip(st.columns(5),items):
                with col:
                    st.markdown(f'<div class="stat-chip"><div class="sc-label">{label}</div>'
                                f'<div class="sc-val" style="color:{color};">{val}</div></div>',
                                unsafe_allow_html=True)
    else:
        st.markdown('<div style="height:180px;display:flex;align-items:center;justify-content:center;'
                    'background:#1e222d;border:1px solid #2a2e39;border-radius:8px;margin-bottom:12px;">'
                    '<div style="text-align:center;font-size:13px;color:#787b86;">'
                    'Configure legs below and click Calculate &amp; Plot</div></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="sec-header">Strategy Builder</div>', unsafe_allow_html=True)

    c1,c2,c3 = st.columns(3)
    with c1: _SS.sp_n_legs = st.selectbox("Legs",list(range(2,7)),index=_SS.sp_n_legs-2,key="sp_legs_sel")
    with c2: _SS.sp_chart_type = st.selectbox("Chart Type",["Candlestick","Line"],key="sp_ct_sel")
    with c3: _SS.sp_tf = st.selectbox("Timeframe",list(TF_MAP.keys()),key="sp_tf_sel")

    n = _SS.sp_n_legs
    legs = []
    cols_legs = st.columns(n)
    for i in range(n):
        with cols_legs[i]:
            st.markdown(f'<div style="font-size:10px;color:#787b86;margin-bottom:6px;background:#2a2e39;'
                        f'padding:2px 8px;border-radius:10px;display:inline-block;">LEG {i+1}</div>',
                        unsafe_allow_html=True)
            idx = st.selectbox("Index",["NIFTY","SENSEX","BANKNIFTY"],key=f"sp_idx_{i}",label_visibility="collapsed")

            exps, exp_err = _load_expiries(idx)
            if exp_err:
                st.markdown(f'<div style="font-size:11px;color:#ff9800;">⏳ Loading expiries…</div>',
                            unsafe_allow_html=True)
                if st.button("🔄",key=f"re_exp_{i}"):
                    _SS.pop(f"expiries_{idx}",None); st.rerun()
                legs.append(dict(index=idx,strike=0,expiry="",cp="CE",
                                 bs="Buy" if i%2==0 else "Sell",ratio=1,ltp=0.0,net=0.0))
                continue

            expiry = st.selectbox("Expiry",exps,key=f"sp_exp_{i}",label_visibility="collapsed")
            strikes, str_err = _load_strikes(idx, expiry)
            if str_err or not strikes:
                st.markdown(f'<div style="font-size:11px;color:#ff9800;">⏳ Loading strikes…</div>',
                            unsafe_allow_html=True)
                if st.button("🔄",key=f"re_str_{i}"):
                    _SS.pop(f"strikes_{idx}_{expiry}",None); st.rerun()
                legs.append(dict(index=idx,strike=0,expiry=expiry,cp="CE",
                                 bs="Buy" if i%2==0 else "Sell",ratio=1,ltp=0.0,net=0.0))
                continue

            atm   = {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(idx,strikes[len(strikes)//2])
            def_s = min(strikes, key=lambda x: abs(x-atm))
            cur   = _SS.get(f"sp_strike_{i}")
            didx  = strikes.index(cur) if cur in strikes else strikes.index(def_s)
            strike = st.selectbox("Strike",strikes,index=didx,key=f"sp_strike_{i}",label_visibility="collapsed")
            cp     = st.selectbox("CE/PE",["CE","PE"],key=f"sp_cp_{i}",label_visibility="collapsed")
            bs     = st.selectbox("Buy/Sell",["Buy","Sell"],index=0 if i%2==0 else 1,key=f"sp_bs_{i}",label_visibility="collapsed")
            ratio  = st.number_input("Ratio",1,10,1,key=f"sp_ratio_{i}",label_visibility="collapsed")

            ltp, signed = 0.0, 0.0
            try:
                ltp    = get_option_price(idx, strike, expiry, cp)
                signed = ltp*ratio if bs=="Buy" else -ltp*ratio
                color  = "#26a69a" if signed>=0 else "#ef5350"
                st.markdown(f'<div style="font-size:11px;color:#787b86;margin-top:3px;">'
                            f'LTP: <span style="color:#d1d4dc;">{ltp:.2f}</span>'
                            f' &nbsp; Net: <span style="color:{color};">{signed:+.2f}</span></div>',
                            unsafe_allow_html=True)
            except Exception:
                st.markdown('<div style="font-size:10px;color:#787b86;margin-top:3px;">LTP: — (fetched on calculate)</div>',
                            unsafe_allow_html=True)

            legs.append(dict(index=idx,strike=strike,expiry=expiry,
                             cp=cp,bs=bs,ratio=ratio,ltp=ltp,net=round(signed,2)))

    valid_legs = [l for l in legs if l["expiry"] and l["strike"] > 0]
    _SS.sp_legs_live = valid_legs
    st.markdown(f'<div style="font-size:10px;color:#26a69a;margin:6px 0;">✓ {len(valid_legs)}/{n} legs ready</div>',
                unsafe_allow_html=True)

    show_greeks = st.checkbox("Show Greeks (Delta, Vega, Gamma, Theta, IV)", value=False, key="sp_show_greeks")
    ui_errors   = _validate_legs_ui(legs)

    if ui_errors:
        st.warning("Complete all leg inputs:\n\n" + "\n".join(f"• {e}" for e in ui_errors))
    else:
        if st.button("⚡  Calculate & Plot", use_container_width=True, type="primary"):
            with st.spinner("Fetching live prices…"):
                fresh_legs = []; fetch_ok = True
                for leg in legs:
                    try:
                        from data_helpers import get_option_price as _gop
                        ltp  = _gop(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
                        sign = 1 if leg["bs"]=="Buy" else -1
                        fresh_legs.append({**leg,"ltp":ltp,"net":round(sign*ltp*leg["ratio"],2)})
                    except Exception as e:
                        st.error(f"Failed LTP Leg {legs.index(leg)+1}: {e}"); fetch_ok=False; break
            if fetch_ok:
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
                        st.info("Check market hours (9:15–3:30 IST, Mon–Fri) and Fyers token validity.")

    if show_greeks and valid_legs and any(l["ltp"]>0 for l in valid_legs):
        st.markdown('<div class="sec-header" style="margin-top:12px;">Net Greeks (Black-Scholes)</div>',
                    unsafe_allow_html=True)
        with st.spinner("Calculating…"):
            try:
                g = calc_greeks_for_legs(valid_legs)
                hi_avg = lo_avg = None
                if _SS.sp_df is not None:
                    closes = _SS.sp_df["close"].dropna()
                    if len(closes) >= 5:
                        hi_avg = round(closes.nlargest(5).mean(),2)
                        lo_avg = round(closes.nsmallest(5).mean(),2)
                metrics = [
                    ("NET DELTA",f"{g['delta']:+.4f}","#2962ff"),
                    ("NET GAMMA",f"{g['gamma']:+.6f}","#ff9800"),
                    ("NET VEGA",f"{g['vega']:+.4f}","#9c27b0"),
                    ("NET THETA",f"{g['theta']:+.4f}","#ef5350"),
                    ("NET IV",f"{g['net_iv']:.2f}%","#26a69a"),
                    ("AVG HIGH",f"{hi_avg:.2f}" if hi_avg else "—","#26a69a"),
                    ("AVG LOW",f"{lo_avg:.2f}" if lo_avg else "—","#ef5350"),
                ]
                for col,(label,val,color) in zip(st.columns(7),metrics):
                    with col:
                        st.markdown(f'<div class="stat-chip"><div class="sc-label">{label}</div>'
                                    f'<div class="sc-val" style="color:{color};">{val}</div></div>',
                                    unsafe_allow_html=True)
            except Exception as e:
                st.warning(f"Greeks failed: {e}")

    if _SS.sp_result:
        r = _SS.sp_result; sv = r["spread"]
        st.markdown("---")
        sv_col,_ = st.columns([1,3])
        with sv_col:
            st.markdown(f'<div style="background:#1e222d;border:1px solid #2a2e39;border-radius:8px;'
                        f'padding:14px;text-align:center;">'
                        f'<div style="font-size:10px;color:#787b86;text-transform:uppercase;">Spread Value</div>'
                        f'<div style="font-size:26px;font-weight:600;'
                        f'color:{"#26a69a" if sv>=0 else "#ef5350"};">{sv:+.2f}</div></div>',
                        unsafe_allow_html=True)
        df_show = pd.DataFrame(r["legs"])[["index","strike","expiry","cp","bs","ratio","ltp","net"]]
        df_show.columns = ["Index","Strike","Expiry","C/P","B/S","Ratio","LTP","Net"]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
