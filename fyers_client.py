import streamlit as st
import requests
import pyotp
import base64
from fyers_apiv3 import fyersModel

# ==============================
# 🔐 SECRETS
# ==============================

CLIENT_ID = st.secrets["FYERS_CLIENT_ID"]
SECRET_KEY = st.secrets["FYERS_SECRET_KEY"]
USERNAME = st.secrets["FYERS_USERNAME"]
PIN = st.secrets["FYERS_PIN"]
TOTP_KEY = st.secrets["FYERS_TOTP_KEY"]

REDIRECT_URI = "https://trade.fyers.in/api-login/redirect-uri/index.html"

# ==============================
# 🔑 LOGIN (ONLY ONCE)
# ==============================

@st.cache_resource
def generate_token():
    session = requests.Session()

    def b64(x):
        return base64.b64encode(str(x).encode()).decode()

    # STEP 1: SEND OTP
    r1 = session.post(
        "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
        json={"fy_id": b64(USERNAME), "app_id": "2"}
    )

    if r1.status_code == 429:
        raise Exception("Rate limited. Wait 2–5 minutes and restart app.")

    r1 = r1.json()

    if "request_key" not in r1:
        raise Exception(f"OTP Step Failed: {r1}")

    # STEP 2: VERIFY TOTP
    otp = pyotp.TOTP(TOTP_KEY).now()

    r2 = session.post(
        "https://api-t2.fyers.in/vagator/v2/verify_otp",
        json={"request_key": r1["request_key"], "otp": otp}
    ).json()

    if "request_key" not in r2:
        raise Exception(f"TOTP Failed: {r2}")

    # STEP 3: VERIFY PIN
    r3 = session.post(
        "https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
        json={
            "request_key": r2["request_key"],
            "identity_type": "pin",
            "identifier": b64(PIN)
        }
    ).json()

    if "data" not in r3:
        raise Exception(f"PIN Failed: {r3}")

    temp_token = r3["data"]["access_token"]

    # STEP 4: AUTH CODE
    app_id = CLIENT_ID.split("-")[0]

    r4 = session.post(
        "https://api-t1.fyers.in/api/v3/token",
        json={
            "fyers_id": USERNAME,
            "app_id": app_id,
            "redirect_uri": REDIRECT_URI,
            "appType": "100",
            "response_type": "code"
        },
        headers={"Authorization": f"Bearer {temp_token}"}
    ).json()

    if "data" not in r4 or "auth_code" not in r4["data"]:
        raise Exception(f"Auth Code Failed: {r4}")

    auth_code = r4["data"]["auth_code"]

    # STEP 5: FINAL TOKEN
    session_model = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_KEY,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code"
    )

    session_model.set_token(auth_code)
    final = session_model.generate_token()

    if "access_token" not in final:
        raise Exception(f"Final Token Failed: {final}")

    return final["access_token"]

# ==============================
# 🚀 FYERS CLIENT
# ==============================

@st.cache_resource
def get_fyers():
    token = generate_token()
    return fyersModel.FyersModel(
        client_id=CLIENT_ID,
        token=token,
        log_path=""
    )

# ==============================
# 📊 EXPIRIES
# ==============================

@st.cache_data(ttl=300)
def get_expiries(index):
    fyers = get_fyers()

    symbol_map = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "SENSEX": "BSE:SENSEX-INDEX"
    }

    if index not in symbol_map:
        raise Exception(f"Invalid index: {index}")

    response = fyers.optionchain({
        "symbol": symbol_map[index],
        "strikecount": 1
    })

    if response.get("s") != "ok":
        raise Exception(f"API Error: {response}")

    expiry_data = response.get("data", {}).get("expiryData", [])

    if not expiry_data:
        raise Exception("No expiry data received")

    return expiry_data

# ==============================
# 🧪 TEST CONNECTION
# ==============================

def test_connection():
    fyers = get_fyers()
    return fyers.get_profile()
