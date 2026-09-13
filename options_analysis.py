"""Option snapshot normalization, filtering, and transparent screening scores."""
from __future__ import annotations

from datetime import date, datetime
from math import sqrt
from typing import Any, Iterable

import numpy as np
import pandas as pd


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def normalize_snapshots(ticker: str, snapshots: Iterable[dict[str, Any]], spot_price: float, today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    rows = []
    for raw in snapshots:
        expiration_raw = raw.get("expiration") or raw.get("expiration_date")
        try:
            expiration = pd.Timestamp(expiration_raw).date()
        except (TypeError, ValueError):
            continue
        bid, ask, strike = (_number(raw.get(key)) for key in ("bid", "ask", "strike"))
        dte = (expiration - today).days
        mid = (bid + ask) / 2 if bid is not None and ask is not None and bid + ask > 0 else None
        spread = (ask - bid) / mid if bid is not None and ask is not None and mid and ask >= bid else None
        rows.append({"ticker": ticker, "contract_symbol": raw.get("contract_symbol") or raw.get("symbol"), "option_type": str(raw.get("option_type", raw.get("type", ""))).lower(), "expiration": expiration.isoformat(), "dte": dte, "strike": strike, "spot_price": spot_price, "bid": bid, "ask": ask, "mid": mid, "bid_ask_spread_pct": spread, "implied_volatility": _number(raw.get("implied_volatility", raw.get("iv"))), "delta": _number(raw.get("delta")), "gamma": _number(raw.get("gamma")), "theta": _number(raw.get("theta")), "vega": _number(raw.get("vega")), "volume": _number(raw.get("volume")), "open_interest": _number(raw.get("open_interest")), "quote_timestamp": raw.get("quote_timestamp")})
    return pd.DataFrame(rows)


def _reject(row: dict[str, Any], reason: str) -> dict[str, Any]:
    row = dict(row)
    row.update({"verdict": "REJECTED", "rejection_reason": reason, "score": 0.0})
    return row


def evaluate_contracts(frame: pd.DataFrame, expected_rv: float, earnings_by_contract: dict[str, dict[str, Any]], *, min_dte: int, max_dte: int, option_type: str, target_delta: float, min_delta: float, max_delta: float, max_spread: float, min_bid: float = 0.05) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for _, source in frame.iterrows():
        row = source.to_dict(); symbol = str(row.get("contract_symbol"))
        def reject(reason: str) -> None: rejected.append(_reject(row, reason))
        if row.get("option_type") not in (option_type, option_type[0]): reject(f"REJECTED: option type is not {option_type}."); continue
        if not (min_dte <= row.get("dte", -1) <= max_dte): reject("REJECTED: option is outside configured DTE."); continue
        bid, ask, strike, spot, iv, delta = (row.get(k) for k in ("bid", "ask", "strike", "spot_price", "implied_volatility", "delta"))
        if bid is None or ask is None or bid < min_bid or ask <= 0 or ask < bid: reject("REJECTED: missing/invalid bid-ask quote or bid below minimum."); continue
        if row.get("bid_ask_spread_pct") is None or row["bid_ask_spread_pct"] > max_spread: reject("REJECTED: bid-ask spread is too wide."); continue
        if any(value is None for value in (strike, spot, iv, delta)) or strike <= 0 or spot <= 0: reject("REJECTED: invalid strike, spot, IV, or delta."); continue
        if iv <= 0 or iv > 10: reject("REJECTED: IV is missing, nonpositive, or unreasonable."); continue
        if not (min_delta <= delta <= max_delta): reject(f"REJECTED: delta {delta:.3f} is outside [{min_delta:.2f}, {max_delta:.2f}]."); continue
        if (option_type == "put" and strike >= spot) or (option_type == "call" and strike <= spot): reject("REJECTED: strike is not out-of-the-money."); continue
        event = earnings_by_contract.get(symbol, {})
        if not event.get("safe"): reject(event.get("reason", "REJECTED: earnings filter failed.")); continue
        expected_move = spot * expected_rv * sqrt(row["dte"] / 252)
        if expected_move <= 0: reject("REJECTED: expected move is invalid."); continue
        row.update({"current_stock_price": spot, "current_stock_price_source": "yfinance adjusted close", "option_price": bid, "option_price_basis": "bid used as the assumed short-sale credit", "iv_rv_ratio": iv / expected_rv, "iv_minus_rv": iv - expected_rv, "expected_move_dollars": expected_move, "distance_from_expected_move": ((spot - strike) if option_type == "put" else (strike - spot)) / expected_move, "premium_per_share": bid, "premium_per_contract": bid * 100, "earnings_date": event.get("earnings_date"), "days_until_earnings": event.get("days_until_earnings")})
        if option_type == "put":
            row.update({"required_cash_collateral": strike * 100, "effective_purchase_price": strike - bid, "put_distance_from_spot_pct": (spot - strike) / spot, "collateral_yield": bid / strike, "simple_annualized_collateral_yield": (bid / strike) * 365 / row["dte"]})
            premium_yield = row["collateral_yield"]
        else:
            row.update({"effective_call_away_price": strike + bid, "call_distance_from_spot_pct": (strike - spot) / spot, "premium_yield_on_stock": bid / spot, "simple_annualized_premium_yield": (bid / spot) * 365 / row["dte"]})
            premium_yield = row["premium_yield_on_stock"]
        row["delta_distance"] = abs(delta - target_delta)
        row["_premium_yield"] = premium_yield
        candidates.append(row)
    if candidates:
        result = pd.DataFrame(candidates)
        def norm(column: str) -> pd.Series:
            values = pd.to_numeric(result[column], errors="coerce").fillna(0); span = values.max() - values.min()
            return (values - values.min()) / span if span else pd.Series(1.0, index=result.index)
        result["score"] = 0.50 * norm("iv_rv_ratio") + 0.25 * norm("_premium_yield") + 0.15 * norm("distance_from_expected_move") - 0.10 * norm("bid_ask_spread_pct")
        result["verdict"] = np.where(result["score"] > 0, np.where(result["distance_from_expected_move"] < 0.75, "CAUTION", "CANDIDATE"), "REJECTED")
        result["why_screened"] = np.where(result["verdict"] == "CAUTION", "Higher IV relative to realized volatility and acceptable premium passed the screen, but the strike is less than 0.75 expected moves away.", "Higher IV relative to realized volatility, premium yield, out-of-the-money distance, liquidity, delta, and earnings filters passed the screen.")
        result["score_explanation"] = "Transparent relative screen: 50% IV/RV, 25% premium yield, 15% distance from expected move, minus 10% spread. Higher is better only versus same-type contracts in this scan; it is not probability, expected return, or a profitability guarantee."
        result["rejection_reason"] = np.where(result["verdict"] == "REJECTED", "REJECTED: computed score is nonpositive.", "")
        result = result[result["verdict"] != "REJECTED"].sort_values("score", ascending=False)
    else:
        result = pd.DataFrame()
    return result, pd.DataFrame(rejected)
