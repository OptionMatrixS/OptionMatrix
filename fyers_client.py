"""
fyers_client.py — Option Matrix
Auth + all data fetching from Fyers API v3.
"""
import os, base64, hashlib, math
import streamlit as st
import pandas as pd
import requests as _req
import pyotp
from datetime import datetime, date
from collections import defaultdict
from urllib.parse import parse_qs, urlparse
from fyers_apiv3 import fyersModel

REDIRECT_URI   = "http://127.0.0.1:8080/"
TOKEN_FILE     = "fyers_token.txt"
RISK_FREE_RATE = 0.065
_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}

def _s(key):
    try:
        if key in st.secrets: return str(st.secrets[key]).strip()
    except Exception: pass
    return os.environ.get(key,"").strip()

def _b64(v): return base64.b64encode(str(v).encode()).decode()

# ── AUTH (friend's exact working pattern) ─────────────────────────────────────
@st.cache_resource(ttl=3600)
def _get_access_token(client_id, secret_key, username, pin, totp_key):
    s = _req.Session()
    r1 = s.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                json={"fy_id":_b64(username),"app_id":"2"},timeout=10)
    if r1.status_code==429: raise RuntimeError("Rate limited (429). Wait 60s.")
    d1=r1.json()
    if d1.get("s")!="ok": raise RuntimeError(f"Step1:{d1}")
    totp=pyotp.TOTP(totp_key).now()
    r2=s.post("https://api-t2.fyers.in/vagator/v2/verify_otp",
              json={"request_key":d1["request_key"],"otp":totp},timeout=10)
    d2=r2.json()
    if d2.get("s")!="ok": raise RuntimeError(f"Step2:{d2} — TOTP_KEY must be Base32 secret not 6-digit code")
    r3=s.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
              json={"request_key":d2["request_key"],"identity_type":"pin","identifier":_b64(pin)},timeout=10)
    d3=r3.json()
    if d3.get("s")!="ok": raise RuntimeError(f"Step3:{d3} — check FYERS_PIN")
    app_id=client_id.split("-")[0]
    r4=s.post("https://api-t1.fyers.in/api/v3/token",
              json={"fyers_id":username,"app_id":app_id,"redirect_uri":REDIRECT_URI,
                    "appType":"100","code_challenge":"","state":"sample",
                    "scope":"","nonce":"","response_type":"code","create_cookie":True},
              headers={"Authorization":f"Bearer {d3['data']['access_token']}"},timeout=10)
    d4=r4.json()
    if d4.get("s")!="ok": raise RuntimeError(f"Step4:{d4}\nRedirect URL must be: {REDIRECT_URI}")
    data=d4.get("data",{})
    auth_code=(data.get("auth")
               or parse_qs(urlparse(d4.get("Url","")).query).get("auth_code",[None])[0]
               or parse_qs(urlparse(data.get("url","")).query).get("auth_code",[None])[0])
    if not auth_code: raise RuntimeError(f"Step4 no auth_code:{d4}")
    app_hash=hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
    r5=s.post("https://api-t1.fyers.in/api/v3/validate-authcode",
              json={"grant_type":"authorization_code","appIdHash":app_hash,"code":auth_code},timeout=10)
    d5=r5.json(); token=d5.get("access_token")
    if not token:
        try:
            sm=fyersModel.SessionModel(client_id=client_id,secret_key=secret_key,
                                        redirect_uri=REDIRECT_URI,response_type="code",
                                        grant_type="authorization_code")
            sm.set_token(auth_code); d5b=sm.generate_token(); token=d5b.get("access_token")
            if not token: raise RuntimeError(f"Step5 both failed:{d5}/{d5b}")
        except Exception as e: raise RuntimeError(f"Step5:{d5}/SDK:{e}")
    return token

def get_token():
    cid=_s("FYERS_CLIENT_ID"); sec=_s("FYERS_SECRET_KEY")
    user=_s("FYERS_USERNAME"); pin=_s("FYERS_PIN"); totp=_s("FYERS_TOTP_KEY")
    miss=[k for k,v in {"FYERS_CLIENT_ID":cid,"FYERS_SECRET_KEY":sec,
           "FYERS_USERNAME":user,"FYERS_PIN":pin,"FYERS_TOTP_KEY":totp}.items() if not v]
    if miss: raise RuntimeError(f"Missing secrets:{miss}\nAdd in Streamlit Cloud→Settings→Secrets")
    return _get_access_token(cid,sec,user,pin,totp)

def get_fyers_client():
    if st.session_state.get("_fc"): return st.session_state._fc
    tok=get_token(); cid=_s("FYERS_CLIENT_ID")
    fc=fyersModel.FyersModel(client_id=cid,is_async=False,token=tok,log_path="")
    st.session_state._fc=fc; return fc

def refresh_token():
    _get_access_token.clear()
    st.session_state.pop("_fc",None)
    for k in list(st.session_state.keys()):
        if k.startswith("expiries_") or k.startswith("strikes_"):
            del st.session_state[k]

# ── EXPIRIES ──────────────────────────────────────────────────────────────────
@st.cache_resource
def _fetch_expiry_map(token, cid, sym):
    try:
        fyers=fyersModel.FyersModel(client_id=cid,token=token,log_path="")
        resp=fyers.optionchain(data={"symbol":sym,"strikecount":1,"timestamp":""})
        if not(resp and resp.get("s")=="ok"): return {}
        raw=resp.get("data",{}).get("expiryData",[])
        parsed=[]
        for e in raw:
            if not isinstance(e,dict): continue
            try: dd,mm,yy4=e["date"].split("-"); dd,mm,yy4=int(dd),int(mm),int(yy4)
            except: continue
            parsed.append((yy4%100,mm,dd,_MONTHS[mm-1]))
        by_month=defaultdict(list)
        for yy,mm,dd,mon in parsed: by_month[(yy,mm)].append(dd)
        last_day={k:max(v) for k,v in by_month.items()}
        result={}
        for yy,mm,dd,mon in parsed:
            is_m=(dd==last_day[(yy,mm)])
            code=f"{yy:02d}{mon}" if is_m else f"{yy:02d}{mm:02d}{dd:02d}"
            label=f"{dd:02d} {mon} {yy:02d} ({'M' if is_m else 'W'})"
            result[label]=code
        return result
    except: return {}

def get_expiries(index):
    ck=f"expiries_{index}"
    if st.session_state.get(ck): return list(st.session_state[ck].keys())
    tok=get_token(); cid=_s("FYERS_CLIENT_ID")
    sym=_UNDERLYING_SYM.get(index.upper(),f"NSE:{index}-INDEX")
    data=_fetch_expiry_map(tok,cid,sym)
    if not data: raise ValueError(f"No expiries for {index} — click Refresh Token")
    st.session_state[ck]=data; return list(data.keys())

def _label_to_code(index,label):
    return st.session_state.get(f"expiries_{index}",{}).get(label,label)

def _code_to_date(code):
    import calendar
    code=code.strip().upper()
    mmap={m:i+1 for i,m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):
        yy=int(code[:2]); mon=code[2:5]; mm=mmap[mon]
        return date(2000+yy,mm,calendar.monthrange(2000+yy,mm)[1])
    return date(2000+int(code[:2]),int(code[2:4]),int(code[4:6]))

def _dte(label,index=""):
    try:
        code=_label_to_code(index,label) if index else label
        return max((_code_to_date(code)-datetime.now().date()).days,1)/365.
    except: return 30/365.

_days_to_expiry=_dte

# ── STRIKES — fetches ALL strikes (strikecount:0) ─────────────────────────────
def get_strikes(index, expiry_label):
    code=_label_to_code(index,expiry_label)
    ck=f"strikes_{index}_{code}"
    if st.session_state.get(ck): return st.session_state[ck]
    try:
        fyers=get_fyers_client()
        sym=_UNDERLYING_SYM.get(index.upper(),f"NSE:{index}-INDEX")
        # strikecount:0 = ALL strikes, not just ±50
        resp=fyers.optionchain(data={"symbol":sym,"strikecount":0,"timestamp":""})
        if resp and resp.get("s")=="ok":
            strikes=sorted({int(float(o["strikePrice"]))
                            for o in resp.get("data",{}).get("optionsChain",[])
                            if isinstance(o,dict) and o.get("strikePrice")})
            if strikes:
                st.session_state[ck]=strikes; return strikes
    except: pass
    atm={"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(index,22800)
    step=50 if index=="NIFTY" else(100 if index=="BANKNIFTY" else 500)
    return list(range(atm-40*step,atm+41*step,step))

# ── SYMBOL BUILDER ────────────────────────────────────────────────────────────
def build_symbol(index,expiry_label,cp,strike):
    exch="BSE" if index in("SENSEX","BANKEX") else "NSE"
    code=_label_to_code(index,expiry_label).strip().upper()
    ot="CE" if cp.upper() in("CE","C") else "PE"
    if any(c.isalpha() for c in code): return f"{exch}:{index}{code}{ot}{strike}"
    yy,mm,dd=code[:2],str(int(code[2:4])),code[4:6]
    return f"{exch}:{index}{yy}{mm}{dd}{ot}{strike}"

# ── LIVE QUOTE ────────────────────────────────────────────────────────────────
def _quote(symbol):
    fyers=get_fyers_client()
    resp=fyers.quotes(data={"symbols":symbol})
    if resp.get("s")!="ok": raise ValueError(f"Quote failed:{symbol}:{resp}")
    v=resp["d"][0]["v"]; ltp=float(v.get("lp",0))
    return {"ltp":ltp,"bid":float(v.get("bid",ltp*.998)),
            "ask":float(v.get("ask",ltp*1.002)),
            "prev_close":float(v.get("prev_close_price",0)),
            "high":float(v.get("high_price",ltp)),"low":float(v.get("low_price",ltp))}

def get_live_quote(index,strike,expiry_label,cp):
    _validate_leg(index,strike,expiry_label,cp)
    return _quote(build_symbol(index,expiry_label,cp,strike))

def get_live_ltp(index,strike,expiry_label,cp):
    return get_live_quote(index,strike,expiry_label,cp)["ltp"]

def get_live_bid_ask_ltp(index,strike,expiry_label,cp):
    q=get_live_quote(index,strike,expiry_label,cp); return q["bid"],q["ask"],q["ltp"]

def get_spot_price(index):
    try: return _quote(_UNDERLYING_SYM.get(index,f"NSE:{index}-INDEX"))["ltp"]
    except: return {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(index,22800)

# ── OPTION CHAIN (for bhavcopy — all strikes, all expiries) ───────────────────
def get_full_option_chain(index_sym):
    """Fetch full option chain. Returns list of dicts with all strikes."""
    try:
        fyers=get_fyers_client()
        resp=fyers.optionchain(data={"symbol":index_sym,"strikecount":0,"timestamp":""})
        if resp and resp.get("s")=="ok":
            return resp.get("data",{})
        return {}
    except: return {}

# ── CANDLES with live-quote fallback ──────────────────────────────────────────
def _fetch_candles(symbol,interval=1,date_str=None):
    if date_str is None: date_str=datetime.now().strftime("%Y-%m-%d")
    fyers=get_fyers_client()
    resp=fyers.history(data={"symbol":symbol,"resolution":str(interval),
                              "date_format":"1","range_from":date_str,
                              "range_to":date_str,"cont_flag":"1"})
    if resp.get("s")!="ok" or not resp.get("candles"): return pd.DataFrame()
    df=pd.DataFrame(resp["candles"],columns=["ts","open","high","low","close","volume"])
    df["time"]=(pd.to_datetime(df["ts"],unit="s")
                .dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata").dt.tz_localize(None))
    return df.drop(columns=["ts"]).set_index("time")

def _get_candles(index,strike,expiry_label,cp,interval=1,date_str=None):
    _validate_leg(index,strike,expiry_label,cp)
    sym=build_symbol(index,expiry_label,cp,strike)
    df=_fetch_candles(sym,interval,date_str)
    if df.empty:
        # Fallback: single live quote as one-row dataframe
        try:
            q=_quote(sym)
            ltp=q["ltp"]
            now=pd.Timestamp.now().floor("min")
            df=pd.DataFrame({"open":[ltp],"high":[ltp],"low":[ltp],
                              "close":[ltp],"volume":[0]},index=[now])
            df.index.name="time"
        except: raise ValueError(f"No data for {sym}. Market may be closed.")
    return df

# ── VALIDATION ────────────────────────────────────────────────────────────────
def _validate_leg(index,strike,expiry,cp):
    if not index: raise ValueError("Index not selected.")
    if not expiry: raise ValueError(f"Expiry not selected for {index}.")
    if not strike or strike<=0: raise ValueError(f"Invalid strike {strike}.")
    if cp not in("CE","PE"): raise ValueError(f"cp must be CE or PE.")

def validate_legs(legs):
    if not legs: raise ValueError("No legs.")
    for i,leg in enumerate(legs):
        try: _validate_leg(leg.get("index",""),leg.get("strike",0),
                           leg.get("expiry",""),leg.get("cp",""))
        except ValueError as e: raise ValueError(f"Leg {i+1}:{e}")

# ── SPREAD OHLCV ──────────────────────────────────────────────────────────────
def get_live_spread_ohlcv(legs,interval=1,date_str=None):
    validate_legs(legs)
    spread=base=None
    for leg in legs:
        df=_get_candles(leg["index"],leg["strike"],leg["expiry"],leg["cp"],interval,date_str)
        price=df["close"]*leg["ratio"]
        price=price if leg["bs"]=="Buy" else -price
        if spread is None: spread,base=price,df.index
        else: spread=spread.reindex(base).add(price.reindex(base),fill_value=0)
    out=pd.DataFrame({"close":spread.values},index=base)
    out["open"]=out["close"].shift(1).fillna(out["close"])
    out["high"]=out[["open","close"]].max(axis=1)
    out["low"]=out[["open","close"]].min(axis=1)
    out=out.reset_index()
    if "index" in out.columns: out=out.rename(columns={"index":"time"})
    return out

# ── BLACK-SCHOLES ──────────────────────────────────────────────────────────────
def _ncdf(x): return (1+math.erf(x/math.sqrt(2)))/2
def _npdf(x): return math.exp(-.5*x*x)/math.sqrt(2*math.pi)

def bs_price(S,K,T,r,sig,cp):
    if T<=0 or sig<=0: return max(0.,(S-K) if cp=="CE" else(K-S))
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    return S*_ncdf(d1)-K*math.exp(-r*T)*_ncdf(d2) if cp=="CE" else K*math.exp(-r*T)*_ncdf(-d2)-S*_ncdf(-d1)

def implied_volatility(mp,S,K,T,r,cp):
    if mp<=0 or S<=0 or K<=0 or T<=0: return 0.
    lo,hi=.001,5.
    for _ in range(200):
        mid=(lo+hi)/2; p=bs_price(S,K,T,r,mid,cp)
        if abs(p-mp)<1e-5: return mid
        lo,hi=(mid,hi) if p<mp else(lo,mid)
    return mid

def bs_greeks(S,K,T,r,sig,cp):
    if T<=0 or sig<=0: return{"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sig*100}
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    pdf=_npdf(d1); g=pdf/(S*sig*math.sqrt(T)); v=S*pdf*math.sqrt(T)/100
    d=_ncdf(d1) if cp=="CE" else _ncdf(d1)-1
    t=(-(S*pdf*sig)/(2*math.sqrt(T))+(-r*K*math.exp(-r*T)*_ncdf(d2) if cp=="CE"
       else r*K*math.exp(-r*T)*_ncdf(-d2)))/365
    return{"delta":round(d,4),"gamma":round(g,6),"vega":round(v,4),"theta":round(t,4),"iv":round(sig*100,2)}

def get_spread_greeks(legs,spots):
    validate_legs(legs); net={"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"ivs":[]}
    for leg in legs:
        try:
            S=float(spots.get(leg["index"],22800)); K=float(leg["strike"])
            T=_dte(leg["expiry"],leg["index"])
            ltp=get_live_ltp(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
            sig=implied_volatility(ltp,S,K,T,RISK_FREE_RATE,leg["cp"])
            g=bs_greeks(S,K,T,RISK_FREE_RATE,sig,leg["cp"])
            sgn=1 if leg["bs"]=="Buy" else -1; ratio=leg["ratio"]
            for k in("delta","gamma","vega","theta"): net[k]+=sgn*ratio*g[k]
            net["ivs"].append(g["iv"])
        except: pass
    return{"delta":round(net["delta"],4),"gamma":round(net["gamma"],6),
           "vega":round(net["vega"],4),"theta":round(net["theta"],4),
           "net_iv":round(sum(net["ivs"])/len(net["ivs"]),2) if net["ivs"] else 0.}

# ── IV SERIES ─────────────────────────────────────────────────────────────────
def get_iv_series_live(index,strike,expiry_label,cp,tf_minutes=5,date_str=None):
    _validate_leg(index,strike,expiry_label,cp)
    df=_get_candles(index,strike,expiry_label,cp,tf_minutes,date_str)
    spot=get_spot_price(index); T=_dte(expiry_label,index); rows=[]
    for ts,row in df.iterrows():
        try: iv=implied_volatility(row["close"],spot,strike,T,RISK_FREE_RATE,cp)
        except: iv=0.
        rows.append({"time":ts,"iv_pct":round(iv*100,2)})
    return pd.DataFrame(rows)

# ── MULTIPLIER — uses live quotes, not candles ────────────────────────────────
def get_multiplier_series_live(sx_strike,sx_expiry,n_strike,n_expiry,interval=1,date_str=None):
    """
    Builds multiplier from candles when available, live quotes as fallback.
    Works outside market hours too.
    """
    # Try candle-based first
    try:
        sx_ce=_get_candles("SENSEX",sx_strike,sx_expiry,"CE",interval,date_str)["close"]
        sx_pe=_get_candles("SENSEX",sx_strike,sx_expiry,"PE",interval,date_str)["close"]
        n_ce =_get_candles("NIFTY", n_strike, n_expiry, "CE",interval,date_str)["close"]
        n_pe =_get_candles("NIFTY", n_strike, n_expiry, "PE",interval,date_str)["close"]
        # Align on common index
        common=sx_ce.index.intersection(sx_pe.index).intersection(n_ce.index).intersection(n_pe.index)
        if len(common)>0:
            sx_s=sx_strike+sx_ce[common]-sx_pe[common]
            n_s =n_strike +n_ce[common] -n_pe[common]
            mult=(sx_s/n_s).round(4)
            return pd.DataFrame({"time":common,"multiplier":mult.values,
                                  "sx_synth":sx_s.values.round(2),
                                  "n_synth":n_s.values.round(2)}).reset_index(drop=True)
    except: pass

    # Fallback: single point from live quotes
    try:
        sx_ce_q=_quote(build_symbol("SENSEX",sx_expiry,"CE",sx_strike))["ltp"]
        sx_pe_q=_quote(build_symbol("SENSEX",sx_expiry,"PE",sx_strike))["ltp"]
        n_ce_q =_quote(build_symbol("NIFTY", n_expiry, "CE",n_strike))["ltp"]
        n_pe_q =_quote(build_symbol("NIFTY", n_expiry, "PE",n_strike))["ltp"]
        sx_s=sx_strike+sx_ce_q-sx_pe_q; n_s=n_strike+n_ce_q-n_pe_q
        mult=round(sx_s/n_s,4) if n_s!=0 else 0
        now=pd.Timestamp.now().floor("min")
        return pd.DataFrame({"time":[now],"multiplier":[mult],
                              "sx_synth":[round(sx_s,2)],"n_synth":[round(n_s,2)]})
    except Exception as e:
        raise ValueError(f"Multiplier failed. Check expiry/strike selection. Detail:{e}")

def render_debug_panel():
    """Admin debug panel for sidebar."""
    with st.expander("🔧 Debug",expanded=False):
        if st.button("Clear Token Cache",key="dbg_clear_tok"): refresh_token(); st.rerun()
        try:
            tok=get_token()
            st.success(f"Token OK ({tok[:20]}…)")
        except Exception as e:
            st.error(f"Token error:{e}")
