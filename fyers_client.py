"""
Fyers API v3 Authentication Module
Supports:
  1. Auto token generation via TOTP + headless login flow
  2. Manual access token paste fallback
"""

import streamlit as st
import requests
import pyotp
import hashlib
import json
import time
import re
from urllib.parse import urlparse, parse_qs


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _get_secret(key: str, default="") -> str:
    """Read from st.secrets or env gracefully."""
    try:
        return st.secrets.get(key, default) or default
    except Exception:
        return default


# ─────────────────────────────────────────────────────
# AUTO TOKEN (headless Fyers login)
# ─────────────────────────────────────────────────────

class FyersAutoAuth:
    """
    Performs headless login to Fyers to get an access token.
    Requires: client_id, secret_key, redirect_uri, fy_id, totp_key, pin.
    All stored in Streamlit secrets.
    """

    AUTH_CODE_URL  = "https://api-t1.fyers.in/api/v3/generate-authcode"
    TOKEN_URL      = "https://api-t1.fyers.in/api/v3/validate-authcode"
    SEND_LOGIN_OTP = "https://api-t1.fyers.in/api/v3/send-login-otp"
    VERIFY_OTP_URL = "https://api-t1.fyers.in/api/v3/verify-otp"
    VERIFY_PIN_URL = "https://api-t1.fyers.in/api/v3/verify-pin"
    TOKEN_URL2     = "https://api-t1.fyers.in/api/v3/token"

    def __init__(self):
        self.client_id    = _get_secret("FYERS_CLIENT_ID")
        self.secret_key   = _get_secret("FYERS_SECRET_KEY")
        self.redirect_uri = _get_secret("FYERS_REDIRECT_URI", "https://trade.fyers.in/api-login/redirect-uri/index.html")
        self.fy_id        = _get_secret("FYERS_FY_ID")
        self.totp_key     = _get_secret("FYERS_TOTP_KEY")
        self.pin          = _get_secret("FYERS_PIN")
        self.session      = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _totp(self) -> str:
        return pyotp.TOTP(self.totp_key).now()

    def generate_token(self) -> tuple[bool, str]:
        """
        Full headless auth flow.
        Returns (success: bool, token_or_error: str)
        """
        try:
            # Step 1 — Send login OTP
            r = self.session.post(self.SEND_LOGIN_OTP, json={"fy_id": self.fy_id, "app_id": "2"})
            data = r.json()
            if data.get("s") != "ok":
                return False, f"Send OTP failed: {data.get('message', data)}"
            request_key = data.get("request_key", "")

            # Step 2 — Verify TOTP
            totp_code = self._totp()
            r = self.session.post(self.VERIFY_OTP_URL, json={
                "request_key": request_key,
                "identity_type": "totp",
                "identifier": totp_code,
            })
            data = r.json()
            if data.get("s") != "ok":
                return False, f"TOTP verify failed: {data.get('message', data)}"
            request_key2 = data.get("request_key", request_key)

            # Step 3 — Verify PIN
            pin_hash = _sha256(_sha256(self.pin))
            r = self.session.post(self.VERIFY_PIN_URL, json={
                "request_key": request_key2,
                "identity_type": "pin",
                "identifier": pin_hash,
            })
            data = r.json()
            if data.get("s") != "ok":
                return False, f"PIN verify failed: {data.get('message', data)}"
            access_token_inner = data.get("data", {}).get("access_token", "")
            if not access_token_inner:
                return False, f"No inner access_token in PIN response: {data}"

            # Step 4 — Get auth code
            app_id_hash = _sha256(f"{self.client_id}:{self.secret_key}")
            r = self.session.post(self.AUTH_CODE_URL, json={
                "fyers_id": self.fy_id,
                "app_id": self.client_id.split("-")[0],
                "redirect_uri": self.redirect_uri,
                "appType": "100",
                "code_challenge": "",
                "state": "None",
                "scope": "",
                "nonce": "",
                "response_type": "code",
                "create_cookie": True,
            }, headers={"Authorization": f"Bearer {access_token_inner}"})
            data = r.json()
            auth_code = data.get("Url", "")
            # Extract code from redirect URL
            if "auth_code=" in auth_code:
                auth_code = parse_qs(urlparse(auth_code).query).get("auth_code", [""])[0]
            elif data.get("s") != "ok":
                return False, f"Auth code step failed: {data.get('message', data)}"

            if not auth_code:
                return False, f"Could not extract auth_code from: {data}"

            # Step 5 — Exchange auth code for access token
            r = self.session.post(self.TOKEN_URL2, json={
                "grant_type": "authorization_code",
                "appIdHash": app_id_hash,
                "code": auth_code,
            })
            data = r.json()
            if data.get("s") != "ok":
                return False, f"Token exchange failed: {data.get('message', data)}"

            access_token = data.get("access_token", "")
            if not access_token:
                return False, f"Empty access_token in final response: {data}"

            return True, access_token

        except Exception as e:
            return False, f"Auth exception: {e}"


def _can_auto_auth() -> bool:
    """Check if all secrets needed for auto-auth are present."""
    required = ["FYERS_CLIENT_ID", "FYERS_SECRET_KEY", "FYERS_FY_ID", "FYERS_TOTP_KEY", "FYERS_PIN"]
    return all(_get_secret(k) for k in required)


# ─────────────────────────────────────────────────────
# MAIN: get_fyers_client()
# ─────────────────────────────────────────────────────

def get_fyers_client():
    """
    Returns a connected FyersModel client or None.
    Tries in order:
      1. Already in session_state
      2. Auto-generate token (if TOTP secrets present)
      3. Manually pasted access token from secrets
    Shows status in sidebar.
    """
    from fyers_apiv3 import fyersModel

    # Already connected
    if st.session_state.get("fyers_client") and st.session_state.get("fyers_token"):
        return st.session_state["fyers_client"]

    client_id = _get_secret("FYERS_CLIENT_ID")
    if not client_id:
        st.sidebar.error("⚠️ FYERS_CLIENT_ID not set in secrets.")
        return None

    # Try auto-auth
    if _can_auto_auth() and not st.session_state.get("fyers_token"):
        with st.sidebar:
            with st.spinner("🔄 Auto-generating Fyers token…"):
                auth = FyersAutoAuth()
                ok, result = auth.generate_token()
            if ok:
                st.session_state["fyers_token"] = result
                st.sidebar.success("✅ Token auto-generated")
            else:
                st.sidebar.warning(f"⚠️ Auto-auth failed: {result}")
                st.sidebar.caption("Falling back to manual token…")

    # Fallback: manual token from secrets
    if not st.session_state.get("fyers_token"):
        manual_token = _get_secret("FYERS_ACCESS_TOKEN")
        if manual_token:
            st.session_state["fyers_token"] = manual_token
            st.sidebar.info("🔑 Using manual access token from secrets.")
        else:
            st.sidebar.error("❌ No Fyers token available. Set secrets or paste token below.")
            return None

    token = st.session_state["fyers_token"]
    full_token = f"{client_id}:{token}" if ":" not in token else token

    try:
        client = fyersModel.FyersModel(
            client_id=client_id,
            token=full_token,
            is_async=False,
            log_path="",
        )
        st.session_state["fyers_client"] = client
        return client
    except Exception as e:
        st.sidebar.error(f"Fyers client error: {e}")
        return None


def clear_fyers_client():
    """Force re-auth on next call."""
    for k in ["fyers_client", "fyers_token"]:
        st.session_state.pop(k, None)
