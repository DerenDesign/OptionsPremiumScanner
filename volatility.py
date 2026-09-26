from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import logging
from math import sqrt
from typing import Iterable

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

@dataclass
class VolatilityResult:
    spot_price: float
    rv_5: float
    rv_20: float
    rv_60: float
    expected_rv: float
    history_end_date: str
    expected_moves: dict[int, dict[str, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def get_adjusted_close_history(symbol: str, period: str = "180d") -> pd.Series:
    
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install yfinance before scanning live data") from exc
    try:
        data = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
    except Exception as exc:
        raise RuntimeError(f"yfinance download failed for {symbol}: {exc}") from exc
    if data is None or data.empty:
        raise ValueError(f"No recent historical closes for {symbol}")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    column = "Adj Close" if "Adj Close" in data.columns else "Close"
    closes = pd.to_numeric(data[column], errors="coerce").dropna()
    if closes.empty:
        raise ValueError(f"No valid historical closes for {symbol}")
    return closes


def _annualized_volatility(returns: pd.Series, length: int) -> float:

    window = returns.dropna().tail(length)
    if len(window) < length:
        raise ValueError(f"Need at least {length} valid daily returns; got {len(window)}")
    value = float(window.std(ddof=1) * sqrt(252))
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"Calculated RV{length} is invalid")
    return value


def calculate_volatility(closes: pd.Series, weights: tuple[float, float, float] = (0.20, 0.50, 0.30), dtes: Iterable[int] = range(1, 8)) -> VolatilityResult:

    prices = pd.to_numeric(closes, errors="coerce").dropna()
    if prices.empty or (prices <= 0).any():
        raise ValueError("Historical prices must contain positive values")
    returns = np.log(prices / prices.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    rv5, rv20, rv60 = (_annualized_volatility(returns, n) for n in (5, 20, 60))
    if not np.isclose(sum(weights), 1.0):
        raise ValueError("RV weights must sum to 1.0")
    expected_rv = weights[0] * rv5 + weights[1] * rv20 + weights[2] * rv60
    spot = float(prices.iloc[-1])
    moves = {}
    for dte in dtes:
        pct = expected_rv * sqrt(float(dte) / 252)
        moves[int(dte)] = {"expected_move_pct": pct, "expected_move_dollars": spot * pct}
    return VolatilityResult(spot, rv5, rv20, rv60, expected_rv, str(prices.index[-1].date()), moves)


def calculate_from_symbol(symbol: str, weights=(0.20, 0.50, 0.30), dtes=range(1, 8)) -> VolatilityResult:
    return calculate_volatility(get_adjusted_close_history(symbol), weights, dtes)
