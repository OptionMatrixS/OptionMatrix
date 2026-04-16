import streamlit as st
import requests
import pyotp
import base64
import hashlib
from fyers_apiv3 import fyersModel

# ==============================
# 🔐 REDIRECT URI (MATCH DASHBOARD)
# ==============================

REDIRECT_URI = "http://127.0.0.1:8080/"   # MUST match Fyers app

# ==============================
# 🔐 SECRET HELPER
# ==============================

def _secret(key):
    try:
        return st.secrets[key]
    except:
        return ""

def b64(x):
    return base64.b64encode(str(x).encode()).decode()

# ==============================
# 🔑 TOKEN GENERATION (TOTP)
# ==============================

def generate_token(client_id, secret_key, username, pin, totp_key):
    session = requests.Session()

    # STEP 1
    r1 = session.post(
        "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
        json={"fy_id": b64(username), "app_id": "2"}
    )

    if r1.status_code == 429:
        raise Exception("Rate limited. Wait 60 seconds.")

    r1 = r1.json()

    # STEP 2
    otp = pyotp.TOTP(totp_key).now()

    r2 = session.post(
        "https://api-t2.fyers.in/vagator/v2/verify_otp",
        json={"request_key": r1["request_key"], "otp": otp}
    ).json()

    # STEP 3
    r3 = session.post(
        "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
        json={
            "request_key": r2["request_key"],
            "identity_type": "pin",
            "identifier": b64(pin)
        }
    ).json()

    temp_token = r3["data"]["access_token"]

    # STEP 4
    app_id = client_id.split("-")[0]

    r4 = session.post(
        "https://api-t1.fyers.in/api/v3/token",
        json={
            "fyers_id": username,
            "app_id": app_id,
            "redirect_uri": REDIRECT_URI,
            "appType": "100",
            "response_type": "code"
        },
        headers={"Authorization": f"Bearer {temp_token}"}
    ).json()

    auth_code = r4["data"]["auth_code"]

    # STEP 5 (NEW METHOD - SHA256)
    app_id_hash = hashlib.sha256(f"{app_id}:{secret_key}".encode()).hexdigest()

    r5 = session.post(
        "https://api-t1.fyers.in/api/v3/validate-authcode",
        json={
            "grant_type": "authorization_code",
            "appIdHash": app_id_hash,
            "code": auth_code,
        }
    ).json()

    if "access_token" not in r5:
        raise Exception(f"Token failed: {r5}")

    return r5["access_token"]

# ==============================
# 🔁 CACHED TOKEN (IMPORTANT FIX)
# ==============================

@st.cache_resource
def _cached_token(client_id, secret_key, username, pin, totp_key):
    return generate_token(client_id, secret_key, username, pin, totp_key)

def get_token():
    client_id  = _secret("FYERS_CLIENT_ID")
    secret_key = _secret("FYERS_SECRET_KEY")
    username   = _secret("FYERS_USERNAME")
    pin        = _secret("FYERS_PIN")
    totp_key   = _secret("FYERS_TOTP_KEY")

    return _cached_token(client_id, secret_key, username, pin, totp_key)

# ==============================
# 🚀 FYERS CLIENT
# ==============================

@st.cache_resource
def get_fyers():
    token = get_token()
    return fyersModel.FyersModel(
        client_id=_secret("FYERS_CLIENT_ID"),
        token=token,
        log_path=""
    )
