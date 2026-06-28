# ⚡ Option Matrix

A multi-tab Streamlit options-analytics platform for Indian derivatives
(NIFTY / BANKNIFTY / FINNIFTY / SENSEX), wired to **Fyers API v3**. Bloomberg/
TradingView dark theme, pure-Python Black-Scholes, SQLite auth with per-tool
access control.

---

## Files (14)

| File | Role |
|------|------|
| `app.py` | Entry point: login gate, sidebar nav, routing, input persistence |
| `auth.py` | SQLite auth, roles, per-tool grants, self-healing admin |
| `styles.py` | Palette, CSS, chip/section helpers, Plotly base layout |
| `fyers_client.py` | TOTP auto-login, token cache, symbols, quotes/candles/chain, Greeks |
| `spread_chart.py` | Tab 1 — multi-leg spread, live feed, candles, Safety Calculator |
| `multiplier_chart.py` | Tab 2 — SENSEX/NIFTY synthetic-future multiplier |
| `iv_calculator.py` | Tab 3 — IV across up to 5 expiries |
| `spread_tracker.py` | Tab 4 — monitor 1–10 diagonal spreads (live ladders) |
| `historical_backtest.py` | Tab 5 — replay a spread over a past trading day |
| `position_analysis.py` | Tab 6 — live position P&L, Greeks, payoff |
| `strategy_builder.py` | Tab 7 — 10 presets, payoff, Greeks, P&L sim |
| `live_bhavcopy.py` | Tab 8 — OPTIDX / OPTSTK chain snapshot, filters, export |
| `quiz.py` + `quiz_data.py` | Tab 9 — NISM-style practice quiz |
| `admin_panel.py` | Approve users, set roles, grant tools, reset/delete |
| `requirements.txt` | Dependencies |

---

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Default admin login (change immediately): **admin / change-me-now**

---

## Deploy on Streamlit Community Cloud

1. Push these files to a **private** GitHub repo (secrets make this account-
   sensitive — see the security note).
2. On streamlit.io, create an app pointing at `app.py`.
3. Add the secrets below under **App → Settings → Secrets**.

### Secrets (`.streamlit/secrets.toml`)

```toml
# Fyers
FYERS_CLIENT_ID = "XXXXXX-100"     # full app id incl. the -100 suffix
FYERS_SECRET_KEY = "your_secret"
FYERS_USERNAME  = "YOUR_FY_ID"     # Fyers client/login id
FYERS_PIN       = "1234"
FYERS_TOTP_KEY  = "BASE32SECRET"   # the TOTP seed, NOT a 6-digit code

# Admin bootstrap (re-seeded on every boot)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "pick-a-strong-one"
```

**Redirect URL** in your Fyers app dashboard must be exactly:

```
http://127.0.0.1:8080/
```

The login flow reads the auth code from that redirect; any mismatch fails at
step 4 with a redirect error.

---

## Three corrections made to the original spec

1. **Lot sizes were stale.** The spec listed NIFTY 75 / BANKNIFTY 35 /
   FINNIFTY 40. Current NSE/BSE values (effective the Jan-2026 series) are
   **NIFTY 65, BANKNIFTY 30, FINNIFTY 60, SENSEX 20**. The app reads the lot
   size **live from Fyers per contract** and falls back to these verified
   values — NSE re-derives lot sizes roughly quarterly, so don't hard-code them
   long-term.

2. **Expiry codes are derived from exchange dates, not broker "(W)/(M)"
   labels.** `get_expiries()` pulls the live `expiryData`, marks the last
   expiry of each month as monthly, and builds the Fyers code itself
   (weekly `YY M DD` → e.g. `26519`; monthly `YYMON` → e.g. `26MAY`). A string
   parser (`_label_to_code`) remains as a fallback. This avoids the "Master not
   found" failures that come from guessing the code format.

3. **Streamlit Cloud has an ephemeral filesystem.** `option_matrix.db` and
   `fyers_token.json` are wiped on every reboot/redeploy/wake. To stay usable,
   the **admin is re-seeded from secrets on every boot**, and the daily token is
   also held in `session_state`. **Member accounts created at runtime will not
   survive a restart** — for durable users, mount a volume or point `DB_PATH`
   (in `auth.py`) at an external database.

---

## ⚠️ Security & testing caveats — read before going live

- **Secrets = account access.** Storing the TOTP seed + PIN means anyone with
  the repo/secrets can log into the Fyers account. Keep the repo private. This
  app only **reads** market data and never places orders — if Fyers offers a
  data-only API app, prefer it.
- **The TOTP auto-login is reverse-engineered.** It uses Fyers' internal
  `vagator` endpoints (`send_login_otp_v2` → `verify_otp` → `verify_pin_v2` →
  `/api/v3/token` → `/api/v3/validate-authcode`). These are **not the official
  documented OAuth flow** and Fyers can change them without notice. The code is
  syntax- and logic-verified and the math is unit-tested, but the live API path
  has **not** been run against a real account here (no credentials). Test with
  your own login first; if step 1 or 2 fails, the order of the vagator calls or
  the `appIdHash` construction is the thing to check.
- **Intraday candles** are only returned during/after market hours on a trading
  day; outside those windows the live-feed and IV tabs fall back to single
  quote snapshots (LTP → previous close when the market is closed).
- **F&O stock list** in the bhavcopy tab is a representative subset; NSE's full
  list changes periodically — extend `FNO_STOCKS` as needed.
- The quiz contains **original practice questions**, not actual NISM exam items.
