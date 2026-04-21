# fyers_client.py

import os, base64, math
import streamlit as st
import pandas as pd
import requests as _req
import pyotp
from datetime import datetime, date
from collections import defaultdict
from urllib.parse import parse_qs, urlparse
from fyers_apiv3 import fyersModel

# ✅ FIXED REDIRECT URI (IMPORTANT)
REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"
TOKEN_FILE   = "fyers_token.txt"
RISK_FREE_RATE = 0.065

_MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN",
           "JUL","AUG","SEP","OCT","NOV","DEC"]

_UNDERLYING_SYM = {
    "SENSEX":     "BSE:SENSEX-INDEX",
    "BANKEX":     "BSE:BANKEX-INDEX",
    "NIFTY":      "NSE:NIFTY50-INDEX",
    "BANKNIFTY":  "NSE:NIFTYBANK-INDEX",
    "FINNIFTY":   "NSE:FINNIFTY-INDEX",
    "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
}

# ─────────────────────────────────────────
# Secrets
# ─────────────────────────────────────────

def _s(key: str) -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except:
        pass
    return os.environ.get(key, "").strip()

def _b64(v) -> str:
    return base64.b64encode(str(v).encode()).decode()

# ─────────────────────────────────────────
# LOGIN (FIXED)
# ─────────────────────────────────────────

def generate_token(client_id, secret_key, username, pin, totp_key):

    app_id = client_id.split("-")[0]

    BASE_URL   = "https://api-t2.fyers.in/vagator/v2"
    BASE_URL_2 = "https://api-t1.fyers.in/api/v3"

    try:
        # STEP 1
        r1 = _req.post(BASE_URL + "/send_login_otp_v2",
            json={"fy_id": _b64(username), "app_id": "2"})
        d1 = r1.json()

        if d1.get("s") != "ok":
            return None, f"Step 1 failed: {d1}"

        # STEP 2
        otp = pyotp.TOTP(totp_key).now()

        # STEP 3
        r2 = _req.post(BASE_URL + "/verify_otp",
            json={"request_key": d1["request_key"], "otp": otp})
        d2 = r2.json()

        if d2.get("s") != "ok":
            return None, f"Step 3 failed: {d2}"

        # STEP 4 (PIN FIXED)
        r3 = _req.post(BASE_URL + "/verify_pin_v2",
            json={
                "request_key": d2["request_key"],
                "identity_type": "pin",
                "identifier": base64.b64encode(str(pin).encode()).decode()
            })
        d3 = r3.json()

        if d3.get("s") != "ok":
            return None, (
                f"Step 4 (verify PIN) failed: {d3}\n"
                "Check FYERS_PIN is correct."
            )

        access_token = d3["data"]["access_token"]

        # STEP 5
        r4 = _req.post(BASE_URL_2 + "/token",
            json={
                "fyers_id": username,
                "app_id": app_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code"
            },
            headers={"Authorization": f"Bearer {access_token}"},
            allow_redirects=False)

        redirect_url = r4.headers.get("Location", "")
        auth_code = parse_qs(urlparse(redirect_url).query).get("auth_code", [None])[0]

        if not auth_code:
            return None, "Auth code not found"

        # STEP 6
        session = fyersModel.SessionModel(
            client_id=client_id,
            secret_key=secret_key,
            redirect_uri=REDIRECT_URI,
            response_type="code",
            grant_type="authorization_code"
        )

        session.set_token(auth_code)
        d5 = session.generate_token()

        token = d5.get("access_token")
        if not token:
            return None, f"Token failed: {d5}"

        return token, None

    except Exception as e:
        return None, str(e)

# ─────────────────────────────────────────
# CACHE TOKEN
# ─────────────────────────────────────────

@st.cache_resource
def _cached_token(cid, sec, user, pin, totp):
    token, err = generate_token(cid, sec, user, pin, totp)
    if token:
        return token
    raise RuntimeError(err)

def get_token():
    cid  = _s("FYERS_CLIENT_ID")
    sec  = _s("FYERS_SECRET_KEY")
    user = _s("FYERS_USERNAME")
    pin  = _s("FYERS_PIN")
    totp = _s("FYERS_TOTP_KEY")

    return _cached_token(cid, sec, user, pin, totp)

def get_fyers_client():
    tok = get_token()
    cid = _s("FYERS_CLIENT_ID")
    return fyersModel.FyersModel(client_id=cid, token=tok, log_path="")

def refresh_token():
    _cached_token.clear()

# ─────────────────────────────────────────
# BASIC FUNCTIONS
# ─────────────────────────────────────────

def get_spot_price(index):
    fyers = get_fyers_client()
    sym = _UNDERLYING_SYM.get(index, f"NSE:{index}-INDEX")
    data = fyers.quotes({"symbols": sym})
    return float(data["d"][0]["v"]["lp"])
