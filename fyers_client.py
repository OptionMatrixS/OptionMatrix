"""
fyers_client.py — Option Matrix
Auth uses friend's exact technique:
  - redirect_uri = http://127.0.0.1:8080/
  - fy_id and pin both b64 encoded
  - appIdHash = SHA256(app_id:secret_key)  ← short app_id
  - validate-authcode endpoint for Step 5
  - ttl=82800 (~23h) — auto-refreshes daily, no manual token needed

Streamlit Cloud → Settings → Secrets:
  FYERS_CLIENT_ID  = "YOURAPP-100"
  FYERS_SECRET_KEY = "YOURSECRET"
  FYERS_USERNAME   = "YOURID"
  FYERS_PIN        = "1234"
  FYERS_TOTP_KEY   = "YOURBASE32SECRET"

Optional bypass (skips all TOTP):
  FYERS_ACCESS_TOKEN = "eyJ..."
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


def _s(key: str) -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, "").strip()

def _b64(v) -> str:
    return base64.b64encode(str(v).encode()).decode()


# ── TOTP auto-login ────────────────────────────────────────────────────────────

@st.cache_resource(ttl=82800)
def _get_access_token(client_id: str, secret_key: str,
                      username: str, pin: str, totp_key: str) -> str:
    """
    Friend's exact working technique. ttl=82800 = ~23h auto-refresh.
    Raises RuntimeError on failure → NOT cached → retries fresh next time.
    """
    s = _req.Session()
    s.headers.update({"Content-Type": "application/json", "Accept": "application/json"})

    # Step 1
    r1 = s.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                json={"fy_id": _b64(username), "app_id": "2"}, timeout=15)
    if r1.status_code == 429:
        raise RuntimeError("Rate-limited (429). Wait ~60s then click Refresh Token.")
    if not r1.text.strip():
        raise RuntimeError(f"Step1: empty response HTTP {r1.status_code}")
    r1d = r1.json()
    if r1d.get("s") != "ok":
        raise RuntimeError(f"Step1 failed: {r1d}")

    # Step 2
    r2 = s.post("https://api-t2.fyers.in/vagator/v2/verify_otp",
                json={"request_key": r1d["request_key"],
                      "otp": pyotp.TOTP(totp_key).now()}, timeout=15)
    if not r2.text.strip():
        raise RuntimeError(f"Step2: empty response HTTP {r2.status_code}")
    r2d = r2.json()
    if r2d.get("s") != "ok":
        raise RuntimeError(
            f"Step2 TOTP failed: {r2d}\n"
            "FYERS_TOTP_KEY must be Base32 secret, NOT the 6-digit code.")

    # Step 3
    r3 = s.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
                json={"request_key": r2d["request_key"],
                      "identity_type": "pin", "identifier": _b64(pin)}, timeout=15)
    if not r3.text.strip():
        raise RuntimeError(f"Step3: empty response HTTP {r3.status_code}")
    r3d = r3.json()
    if r3d.get("s") != "ok":
        raise RuntimeError(f"Step3 PIN failed: {r3d}. Check FYERS_PIN.")
    bearer = r3d["data"]["access_token"]

    # Step 4
    app_id = client_id.split("-")[0]
    r4 = s.post("https://api-t1.fyers.in/api/v3/token", json={
        "fyers_id": username, "app_id": app_id,
        "redirect_uri": REDIRECT_URI, "appType": "100",
        "code_challenge": "", "state": "sample",
        "scope": "", "nonce": "", "response_type": "code", "create_cookie": True,
    }, headers={"Authorization": f"Bearer {bearer}"}, timeout=15)
    if not r4.text.strip():
        raise RuntimeError(f"Step4: empty response HTTP {r4.status_code}")
    r4d = r4.json()

    try:
        st.session_state["_debug_step4"] = str(r4d)
    except Exception:
        pass

    if r4d.get("s") != "ok":
        raise RuntimeError(
            f"Step4 failed: {r4d}\n"
            f"→ redirectUrl mismatch: set Fyers dashboard Redirect URL to: {REDIRECT_URI}\n"
            f"→ apptype mismatch: FYERS_CLIENT_ID must end in -100")

    data      = r4d.get("data", {})
    auth_code = (
        data.get("auth_code")
        or data.get("auth")
        or parse_qs(urlparse(r4d.get("Url",  "")).query).get("auth_code", [None])[0]
        or parse_qs(urlparse(r4d.get("url",  "")).query).get("auth_code", [None])[0]
        or parse_qs(urlparse(data.get("Url", "")).query).get("auth_code", [None])[0]
        or parse_qs(urlparse(data.get("url", "")).query).get("auth_code", [None])[0]
    )

    try:
        st.session_state["_debug_auth_code"] = auth_code or "NOT FOUND"
    except Exception:
        pass

    if not auth_code:
        raise RuntimeError(
            f"Step4: no auth_code found in response: {r4d}\n"
            f"Redirect URL in Fyers dashboard must be: {REDIRECT_URI}")

    # Step 5 — validate-authcode (short app_id:secret_key hash)
    app_id_hash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()
    r5 = s.post("https://api-t1.fyers.in/api/v3/validate-authcode", json={
        "grant_type": "authorization_code",
        "appIdHash":  app_id_hash,
        "code":       auth_code,
    }, timeout=15)
    if not r5.text.strip():
        raise RuntimeError(f"Step5: empty response HTTP {r5.status_code}")
    r5d   = r5.json()
    token = r5d.get("access_token")
    if token:
        return token

    # Fallback: SDK SessionModel
    try:
        session = fyersModel.SessionModel(
            client_id=client_id, secret_key=secret_key,
            redirect_uri=REDIRECT_URI, response_type="code",
            grant_type="authorization_code")
        session.set_token(auth_code)
        r5d2  = session.generate_token()
        token = r5d2.get("access_token")
        if token:
            return token
        raise RuntimeError(
            f"Step5 both methods failed:\n"
            f"  validate-authcode → {r5d}\n"
            f"  SDK fallback      → {r5d2}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Step5 failed: {r5d}\nSDK: {e}")


def get_token() -> str:
    direct = _s("FYERS_ACCESS_TOKEN")
    if direct and len(direct) > 20:
        return direct
    cid  = _s("FYERS_CLIENT_ID")
    sec  = _s("FYERS_SECRET_KEY")
    user = _s("FYERS_USERNAME")
    pin  = _s("FYERS_PIN")
    totp = _s("FYERS_TOTP_KEY")
    missing = [k for k, v in {
        "FYERS_CLIENT_ID": cid, "FYERS_SECRET_KEY": sec,
        "FYERS_USERNAME": user, "FYERS_PIN": pin, "FYERS_TOTP_KEY": totp,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing secrets: {', '.join(missing)}\n"
            "Streamlit Cloud → ⋮ → Settings → Secrets")
    return _get_access_token(cid, sec, user, pin, totp)


def get_fyers_client():
    if st.session_state.get("_fc"):
        return st.session_state._fc
    tok = get_token()
    fc  = fyersModel.FyersModel(
        client_id=_s("FYERS_CLIENT_ID"),
        is_async=False, token=tok, log_path="")
    st.session_state._fc = fc
    return fc


def refresh_token():
    _get_access_token.clear()
    _fetch_expiry_map.clear()   # clear cached strikes/expiries too
    for k in list(st.session_state.keys()):
        if k in ("_fc","_debug_step4","_debug_auth_code") \
           or k.startswith("expiries_") or k.startswith("strikes_"):
            st.session_state.pop(k, None)


def render_debug_panel():
    with st.expander("🔧 Fyers Auth Debug", expanded=False):
        st.code(st.session_state.get("_debug_step4", "No login attempt yet"), language="json")
        st.markdown(f"**auth_code:** `{st.session_state.get('_debug_auth_code','—')}`")


# ── expiries ───────────────────────────────────────────────────────────────────

@st.cache_resource
def _fetch_expiry_map(token: str, cid: str, sym: str) -> dict:
    try:
        fyers = fyersModel.FyersModel(client_id=cid, token=token, log_path="")
        resp  = fyers.optionchain(data={"symbol": sym, "strikecount": 500, "timestamp": ""})
        if not (resp and resp.get("s") == "ok"):
            return {}
        parsed = []
        for e in resp.get("data", {}).get("expiryData", []):
            if not isinstance(e, dict): continue
            try:
                dd, mm, yy4 = e["date"].split("-")
                parsed.append((int(yy4)%100, int(mm), int(dd), _MONTHS[int(mm)-1]))
            except Exception:
                continue
        by_month = defaultdict(list)
        for yy, mm, dd, mon in parsed:
            by_month[(yy,mm)].append(dd)
        last_day = {k: max(v) for k, v in by_month.items()}
        result   = {}
        for yy, mm, dd, mon in parsed:
            is_m  = (dd == last_day[(yy,mm)])
            code  = f"{yy:02d}{mon}" if is_m else f"{yy:02d}{mm:02d}{dd:02d}"
            label = f"{dd:02d} {mon} {yy:02d} ({'M' if is_m else 'W'})"
            result[label] = code
        return result
    except Exception:
        return {}


def get_expiries(index: str) -> list:
    ck = f"expiries_{index}"
    if st.session_state.get(ck):
        return list(st.session_state[ck].keys())
    tok  = get_token()
    cid  = _s("FYERS_CLIENT_ID")
    sym  = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
    data = _fetch_expiry_map(tok, cid, sym)
    if not data:
        raise ValueError(f"No expiries from Fyers for {index}. Click Refresh Token.")
    st.session_state[ck] = data
    return list(data.keys())


def _label_to_code(index: str, label: str) -> str:
    return st.session_state.get(f"expiries_{index}", {}).get(label, label)


def _code_to_date(code: str) -> date:
    import calendar
    code = code.strip().upper()
    mmap = {m: i+1 for i, m in enumerate(_MONTHS)}
    if any(c.isalpha() for c in code):
        yy = int(code[:2]); mon = code[2:5]; mm = mmap[mon]
        return date(2000+yy, mm, calendar.monthrange(2000+yy, mm)[1])
    return date(2000+int(code[:2]), int(code[2:4]), int(code[4:6]))


def _dte(label: str, index: str = "") -> float:
    try:
        code = _label_to_code(index, label) if index else label
        return max((_code_to_date(code) - datetime.now().date()).days, 1) / 365.0
    except Exception:
        return 30 / 365.0

_days_to_expiry = _dte


def get_strikes(index: str, expiry_label: str) -> list:
    """
    Fetch ALL tradeable strikes for this index+expiry from Fyers.
    Uses timestamp= expiry_date so Fyers returns strikes for that specific expiry.
    strikecount=500 ensures we get the full chain (Fyers caps at available strikes).
    Falls back to live-spot-based range if API fails.
    """
    code = _label_to_code(index, expiry_label)
    ck   = f"strikes_{index}_{code}"
    if st.session_state.get(ck):
        return st.session_state[ck]
    try:
        sym  = _UNDERLYING_SYM.get(index.upper(), f"NSE:{index}-INDEX")
        fyers = get_fyers_client()

        # Pass the expiry date as timestamp so Fyers returns
        # strikes specific to that expiry, not just ATM ± N
        try:
            exp_date = _code_to_date(code).strftime("%Y-%m-%d")
        except Exception:
            exp_date = ""

        resp = fyers.optionchain(data={
            "symbol":      sym,
            "strikecount": 500,       # large enough to get full chain
            "timestamp":   exp_date,  # filter by expiry date
        })
        if resp and resp.get("s") == "ok":
            chain = resp.get("data", {}).get("optionsChain", [])
            strikes = sorted({
                int(float(o["strikePrice"]))
                for o in chain
                if isinstance(o, dict) and "strikePrice" in o
            })
            if strikes:
                st.session_state[ck] = strikes
                return strikes
    except Exception:
        pass

    # Fallback: build range around live spot price ± 40 strikes
    try:
        spot = get_spot_price(index)
    except Exception:
        spot = {"NIFTY": 22800, "SENSEX": 82500, "BANKNIFTY": 48000}.get(index, 22800)
    step = 50 if index == "NIFTY" else (100 if index == "BANKNIFTY" else 500)
    atm  = int(round(spot / step) * step)
    return list(range(atm - 60*step, atm + 61*step, step))


def build_symbol(index: str, expiry_label: str, cp: str, strike: int) -> str:
    exch = "BSE" if index in ("SENSEX","BANKEX") else "NSE"
    code = _label_to_code(index, expiry_label).strip().upper()
    ot   = "CE" if cp.upper() in ("CE","C") else "PE"
    if any(c.isalpha() for c in code):
        return f"{exch}:{index}{code}{ot}{strike}"
    yy, mm, dd = code[:2], str(int(code[2:4])), code[4:6]
    return f"{exch}:{index}{yy}{mm}{dd}{ot}{strike}"


def _fetch_candles(symbol: str, interval=1, date_str=None) -> pd.DataFrame:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    resp = get_fyers_client().history(data={
        "symbol": symbol, "resolution": str(interval),
        "date_format": "1", "range_from": date_str,
        "range_to": date_str, "cont_flag": "1"})
    if resp.get("s") != "ok" or not resp.get("candles"):
        return pd.DataFrame()
    df = pd.DataFrame(resp["candles"], columns=["ts","open","high","low","close","volume"])
    df["time"] = (pd.to_datetime(df["ts"], unit="s")
                  .dt.tz_localize("UTC").dt.tz_convert("Asia/Kolkata").dt.tz_localize(None))
    return df.drop(columns=["ts"]).set_index("time")


def _get_candles(index, strike, expiry_label, cp, interval=1, date_str=None):
    _validate_leg(index, strike, expiry_label, cp)
    sym = build_symbol(index, expiry_label, cp, strike)
    df  = _fetch_candles(sym, interval, date_str)
    if df.empty:
        raise ValueError(f"No data for {sym}. Check the date is a trading day.")
    return df


def _quote(symbol: str) -> dict:
    resp = get_fyers_client().quotes(data={"symbols": symbol})
    if resp.get("s") != "ok":
        raise ValueError(f"Quote failed for {symbol}: {resp}")
    v = resp["d"][0]["v"]; ltp = float(v.get("lp", 0))
    return {"ltp": ltp, "bid": float(v.get("bid", ltp*0.998)),
            "ask": float(v.get("ask", ltp*1.002)),
            "prev_close": float(v.get("prev_close_price", 0)),
            "high": float(v.get("high_price", ltp)),
            "low":  float(v.get("low_price",  ltp))}

def get_live_quote(i,s,e,c):    _validate_leg(i,s,e,c); return _quote(build_symbol(i,e,c,s))
def get_live_ltp(i,s,e,c):      return get_live_quote(i,s,e,c)["ltp"]
def get_live_bid_ask_ltp(i,s,e,c): q=get_live_quote(i,s,e,c); return q["bid"],q["ask"],q["ltp"]
def get_spot_price(index: str) -> float:
    try:    return _quote(_UNDERLYING_SYM.get(index, f"NSE:{index}-INDEX"))["ltp"]
    except: return {"NIFTY":22800,"SENSEX":82500,"BANKNIFTY":48000}.get(index,22800)


def _validate_leg(index, strike, expiry, cp):
    if not index:                 raise ValueError("Index not selected.")
    if not expiry:                raise ValueError(f"Expiry not selected for {index}.")
    if not strike or strike <= 0: raise ValueError(f"Invalid strike {strike}.")
    if cp not in ("CE","PE"):     raise ValueError("cp must be CE or PE.")

def validate_legs(legs):
    if not legs: raise ValueError("No legs.")
    for i, leg in enumerate(legs):
        try:
            _validate_leg(leg.get("index",""), leg.get("strike",0),
                          leg.get("expiry",""), leg.get("cp",""))
        except ValueError as e:
            raise ValueError(f"Leg {i+1}: {e}")


def get_live_spread_ohlcv(legs, interval=1, date_str=None) -> pd.DataFrame:
    validate_legs(legs)
    spread = base = None
    for leg in legs:
        df    = _get_candles(leg["index"],leg["strike"],leg["expiry"],
                             leg["cp"],interval,date_str)
        price = df["close"] * leg["ratio"]
        price = price if leg["bs"]=="Buy" else -price
        if spread is None: spread, base = price, df.index
        else: spread = spread.reindex(base).add(price.reindex(base), fill_value=0)
    out = pd.DataFrame({"close": spread.values}, index=base)
    out["open"] = out["close"].shift(1).fillna(out["close"])
    out["high"] = out[["open","close"]].max(axis=1)
    out["low"]  = out[["open","close"]].min(axis=1)
    out = out.reset_index()
    if "index" in out.columns: out = out.rename(columns={"index":"time"})
    return out


def _ncdf(x): return (1+math.erf(x/math.sqrt(2)))/2
def _npdf(x): return math.exp(-.5*x*x)/math.sqrt(2*math.pi)

def bs_price(S,K,T,r,sig,cp):
    if T<=0 or sig<=0: return max(0.,(S-K) if cp=="CE" else (K-S))
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    return S*_ncdf(d1)-K*math.exp(-r*T)*_ncdf(d2) if cp=="CE" \
        else K*math.exp(-r*T)*_ncdf(-d2)-S*_ncdf(-d1)

def implied_volatility(mp,S,K,T,r,cp):
    if mp<=0 or S<=0 or K<=0 or T<=0: return 0.
    lo,hi=.001,5.
    for _ in range(200):
        mid=(lo+hi)/2; p=bs_price(S,K,T,r,mid,cp)
        if abs(p-mp)<1e-5: return mid
        lo,hi=(mid,hi) if p<mp else (lo,mid)
    return mid

def bs_greeks(S,K,T,r,sig,cp):
    if T<=0 or sig<=0:
        return {"delta":0,"gamma":0,"vega":0,"theta":0,"iv":sig*100}
    d1=(math.log(S/K)+(r+.5*sig**2)*T)/(sig*math.sqrt(T)); d2=d1-sig*math.sqrt(T)
    pdf=_npdf(d1); g=pdf/(S*sig*math.sqrt(T)); v=S*pdf*math.sqrt(T)/100
    d  =_ncdf(d1) if cp=="CE" else _ncdf(d1)-1
    th =(-(S*pdf*sig)/(2*math.sqrt(T)) +
         (-r*K*math.exp(-r*T)*_ncdf(d2) if cp=="CE"
          else r*K*math.exp(-r*T)*_ncdf(-d2))) / 365
    return {"delta":round(d,4),"gamma":round(g,6),
            "vega":round(v,4),"theta":round(th,4),"iv":round(sig*100,2)}

def get_spread_greeks(legs, spots):
    validate_legs(legs)
    net={"delta":0.,"gamma":0.,"vega":0.,"theta":0.,"ivs":[]}
    for leg in legs:
        try:
            S=float(spots.get(leg["index"],22800)); K=float(leg["strike"])
            T=_dte(leg["expiry"],leg["index"])
            ltp=get_live_ltp(leg["index"],leg["strike"],leg["expiry"],leg["cp"])
            sig=implied_volatility(ltp,S,K,T,RISK_FREE_RATE,leg["cp"])
            g=bs_greeks(S,K,T,RISK_FREE_RATE,sig,leg["cp"])
            sgn=1 if leg["bs"]=="Buy" else -1; ratio=leg["ratio"]
            for k in ("delta","gamma","vega","theta"): net[k]+=sgn*ratio*g[k]
            net["ivs"].append(g["iv"])
        except Exception: pass
    return {"delta":round(net["delta"],4),"gamma":round(net["gamma"],6),
            "vega":round(net["vega"],4),"theta":round(net["theta"],4),
            "net_iv":round(sum(net["ivs"])/len(net["ivs"]),2) if net["ivs"] else 0.}


def get_iv_series_live(index,strike,expiry_label,cp,tf_minutes=5,date_str=None):
    _validate_leg(index,strike,expiry_label,cp)
    df=_get_candles(index,strike,expiry_label,cp,tf_minutes,date_str)
    spot=get_spot_price(index); T=_dte(expiry_label,index); rows=[]
    for ts,row in df.iterrows():
        try:    iv=implied_volatility(row["close"],spot,strike,T,RISK_FREE_RATE,cp)
        except: iv=0.
        rows.append({"time":ts,"iv_pct":round(iv*100,2)})
    return pd.DataFrame(rows)


def get_multiplier_series_live(sx_strike,sx_expiry,n_strike,n_expiry,
                                interval=1,date_str=None):
    for i,s,e,c in [("SENSEX",sx_strike,sx_expiry,"CE"),
                    ("SENSEX",sx_strike,sx_expiry,"PE"),
                    ("NIFTY", n_strike, n_expiry, "CE"),
                    ("NIFTY", n_strike, n_expiry, "PE")]:
        _validate_leg(i,s,e,c)
    sx_ce=_get_candles("SENSEX",sx_strike,sx_expiry,"CE",interval,date_str)["close"]
    sx_pe=_get_candles("SENSEX",sx_strike,sx_expiry,"PE",interval,date_str)["close"]
    n_ce =_get_candles("NIFTY", n_strike, n_expiry, "CE",interval,date_str)["close"]
    n_pe =_get_candles("NIFTY", n_strike, n_expiry, "PE",interval,date_str)["close"]
    sx_s=sx_strike+sx_ce-sx_pe; n_s=n_strike+n_ce-n_pe; mult=(sx_s/n_s).round(4)
    return pd.DataFrame({"time":sx_s.index,"multiplier":mult.values,
                         "sx_synth":sx_s.values.round(2),
                         "n_synth":n_s.values.round(2)}).reset_index(drop=True)
