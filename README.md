# ⚡ Option Matrix — Setup Guide

## Folder structure
```
option_matrix/
├── app.py              ← Entry point  (streamlit run app.py)
├── auth.py             ← Login / register / SQLite user DB
├── styles.py           ← Global TradingView dark theme CSS
├── data_helpers.py     ← All data generators  ← REPLACE WITH ANGELONE API
├── requirements.txt
└── pages/
    ├── __init__.py
    ├── spread_chart.py     ← Spread Chart Builder
    ├── iv_calculator.py    ← IV Calculator (Black-Scholes)
    ├── multiplier_chart.py ← SENSEX/NIFTY Synthetic Multiplier
    └── admin_panel.py      ← Admin: approve users, grant tools
```

## Quick start
```bash
pip install -r requirements.txt
streamlit run app.py
```

Default admin login: `admin` / `admin123`
Change this immediately in production via Admin Panel → All Members.

## User flow
1. User visits the site → clicks **Create Account** → fills username/email/password
2. Account is created with `role = pending`
3. You log in as admin → **Admin Panel → Pending** tab → approve and tick which tools to grant
4. User can now log in and access approved tools

## Admin capabilities
- Approve / reject pending accounts
- Grant per-tool access: Spread Chart | IV Calculator | Multiplier
- Set subscription plan (free / basic_5 / basic_10 / premium)
- Promote any user to admin
- Reset any user's password
- Delete accounts
- Add users manually

## Subscription plans (informational, manual for now)
| Plan      | Price       | Notes                        |
|-----------|-------------|------------------------------|
| free      | ₹0          | No tools until manually granted |
| basic_5   | ₹5/month    | Spread Chart                 |
| basic_10  | ₹10/month   | Spread + IV Calculator       |
| premium   | Custom      | All tools                    |

Wire up Razorpay / UPI webhook → auto-approve tools on payment.

## Connecting AngelOne API
Open `data_helpers.py` and replace the 3 functions marked `# ← REPLACE WITH ANGELONE API`:

### 1. get_option_price()
```python
# AngelOne SmartAPI — getOptionChainData
from SmartApi import SmartConnect
def get_option_price(index, strike, expiry, cp):
    # Use angel.getOptionChainData(exchange, tradingsymbol, strikePrice, expiryDate)
    # or subscribe to MarketFeed WebSocket for live LTP
    pass
```

### 2. generate_spread_ohlcv()
```python
# Fetch historical candles for each leg, compute spread bar-by-bar
def generate_spread_ohlcv(legs, tf_minutes):
    # angel.getCandleData(exchange, symboltoken, interval, fromdate, todate)
    pass
```

### 3. get_iv_series() and get_multiplier_series()
```python
# Same pattern: fetch historical LTPs, apply BS solver / synthetic formula
```

## Environment variables (for production)
```bash
# .env or Streamlit secrets.toml
ANGELONE_API_KEY=your_key
ANGELONE_CLIENT_ID=your_client_id
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_SECRET=your_totp
```

Access in code: `st.secrets["ANGELONE_API_KEY"]`

## Deploy to Streamlit Cloud
1. Push folder to GitHub
2. Go to share.streamlit.io → New app → point to `app.py`
3. Add secrets in the Streamlit Cloud dashboard
4. The SQLite DB (`option_matrix.db`) persists on the server volume

For production with multiple users, consider switching SQLite → PostgreSQL (Supabase free tier works well).
