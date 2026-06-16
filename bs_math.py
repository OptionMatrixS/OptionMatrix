"""
Pure-Python Black-Scholes math — no scipy dependency.
"""

import math


def _norm_cdf(x: float) -> float:
    """Abramowitz & Stegun approximation of N(x)."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> float:
    """
    Black-Scholes price.
    S     = spot, K = strike, T = time in years, r = risk-free rate, sigma = IV
    opt_type: "CE" or "PE"
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, (S - K) if opt_type == "CE" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> dict:
    if T <= 0 or sigma <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    phi_d1 = math.exp(-0.5 * d1 ** 2) / math.sqrt(2 * math.pi)

    gamma = phi_d1 / (S * sigma * math.sqrt(T))
    vega  = S * phi_d1 * math.sqrt(T) / 100  # per 1% IV move

    if opt_type == "CE":
        delta = nd1
        theta = (-(S * phi_d1 * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * nd2) / 365
    else:
        delta = nd1 - 1
        theta = (-(S * phi_d1 * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def implied_volatility(market_price: float, S: float, K: float, T: float,
                       r: float, opt_type: str,
                       iterations: int = 200, tol: float = 1e-5) -> float:
    """
    Bisection search for implied volatility.
    Returns IV as a decimal (e.g. 0.18 = 18%).
    Returns 0.0 if not solvable.
    """
    if T <= 0 or market_price <= 0:
        return 0.0
    lo, hi = 1e-6, 10.0
    for _ in range(iterations):
        mid = (lo + hi) / 2
        price = bs_price(S, K, T, r, mid, opt_type)
        diff = price - market_price
        if abs(diff) < tol:
            return mid
        if diff < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def payoff_at_expiry(legs: list[dict], spot: float) -> float:
    """
    Calculate total P&L at expiry for a list of legs.
    Each leg: {opt_type, strike, premium, qty, direction}
    direction: 1 = buy, -1 = sell
    """
    total = 0.0
    for leg in legs:
        K   = leg["strike"]
        prem = leg["premium"]
        qty  = leg["qty"]       # signed lots × lot_size
        d    = leg["direction"] # +1 buy / -1 sell
        if leg["opt_type"] == "CE":
            intrinsic = max(0, spot - K)
        else:
            intrinsic = max(0, K - spot)
        total += d * qty * (intrinsic - prem)
    return total
