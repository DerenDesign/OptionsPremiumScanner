"""Orchestration for a research-only short-options scan."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

import pandas as pd

import config
from events import get_next_earnings_date, is_earnings_safe
from options_analysis import evaluate_contracts, normalize_snapshots
from volatility import calculate_from_symbol

LOGGER = logging.getLogger(__name__)
WARNINGS = [
    "Delayed Alpaca data may not match current executable quotes.",
    "Use current broker quotes before placing an order.",
    "This scanner does not model earnings, news jumps, dividends, early assignment, taxes, or portfolio concentration.",
    "A cash-secured put may result in assignment of 100 shares.",
    "A covered call caps upside above the strike while retaining stock downside.",
]


def _occ_details(contract_symbol: str) -> dict[str, Any]:
    """Parse standard OCC symbols such as AAPL260918P00100000."""
    text = str(contract_symbol).strip()
    if len(text) < 15:
        return {}
    try:
        marker = len(text) - 9
        if marker < 6 or text[marker] not in "CP":
            return {}
        expiry = datetime.strptime(text[marker - 6:marker], "%y%m%d").date().isoformat()
        return {"option_type": text[marker].lower(), "expiration": expiry, "strike": int(text[marker + 1:]) / 1000}
    except (StopIteration, ValueError):
        return {}


def get_alpaca_option_snapshots(symbol: str, api_key: str, api_secret: str) -> list[dict[str, Any]]:
    """Fetch snapshots through alpaca-py; this adapter is the only SDK-specific surface."""
    if not api_key or not api_secret:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_API_SECRET are required")
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        from alpaca.data.enums import OptionsFeed
        client = OptionHistoricalDataClient(api_key, api_secret)
        request = OptionChainRequest(underlying_symbol=symbol, feed=OptionsFeed.INDICATIVE)
        chain = client.get_option_chain(request)
    except Exception as exc:
        raise RuntimeError(f"Alpaca option-chain request failed for {symbol}: {exc}") from exc
    rows = []
    for contract_symbol, snapshot in (chain or {}).items():
        contract = getattr(snapshot, "latest_quote", None)
        greeks = getattr(snapshot, "greeks", None)
        details = getattr(snapshot, "symbol", None)
        parsed = _occ_details(contract_symbol)
        rows.append({
            "contract_symbol": contract_symbol,
            "option_type": getattr(details, "option_type", None) or getattr(snapshot, "option_type", None) or parsed.get("option_type"),
            "expiration": getattr(details, "expiration_date", None) or getattr(snapshot, "expiration_date", None) or parsed.get("expiration"),
            "strike": getattr(details, "strike_price", None) or getattr(snapshot, "strike_price", None) or parsed.get("strike"),
            "bid": getattr(contract, "bid_price", None), "ask": getattr(contract, "ask_price", None),
            "implied_volatility": getattr(snapshot, "implied_volatility", None),
            "delta": getattr(greeks, "delta", None), "gamma": getattr(greeks, "gamma", None),
            "theta": getattr(greeks, "theta", None), "vega": getattr(greeks, "vega", None),
            "volume": getattr(snapshot, "volume", None), "open_interest": getattr(snapshot, "open_interest", None),
            "quote_timestamp": getattr(contract, "timestamp", None),
        })
    return rows


def _event_for_contract(event: dict[str, Any], today: date, expiration: date) -> dict[str, Any]:
    earnings_date = event.get("earnings_date")
    parsed = date.fromisoformat(earnings_date) if earnings_date else None
    result = is_earnings_safe(today, expiration, parsed, config.EARNINGS_BUFFER_DAYS)
    result["earnings_time"] = event.get("earnings_time")
    return result


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame()


def scan_tickers(tickers: list[str], min_dte: int, max_dte: int, scan_puts: bool = True, scan_calls: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return best put per ticker, best call per ticker, and all useful rejections."""
    today = date.today()
    all_puts: list[pd.DataFrame] = []; all_calls: list[pd.DataFrame]; all_calls = []
    rejections: list[dict[str, Any]] = []
    from os import getenv
    for ticker in dict.fromkeys(t.strip().upper() for t in tickers if t.strip()):
        try:
            vol = calculate_from_symbol(ticker, (config.RV5_WEIGHT, config.RV20_WEIGHT, config.RV60_WEIGHT), range(min_dte, max_dte + 1))
            event = get_next_earnings_date(ticker, today, today + timedelta(days=90), getenv("FMP_API_KEY", ""))
            raw = get_alpaca_option_snapshots(ticker, getenv("ALPACA_API_KEY", ""), getenv("ALPACA_API_SECRET", ""))
            frame = normalize_snapshots(ticker, raw, vol.spot_price, today)
            if frame.empty:
                raise ValueError("No valid current option quote")
            for option_type, enabled, target, lower, upper, destination in (("put", scan_puts, config.PUT_TARGET_DELTA, config.PUT_MIN_DELTA, config.PUT_MAX_DELTA, all_puts), ("call", scan_calls, config.CALL_TARGET_DELTA, config.CALL_MIN_DELTA, config.CALL_MAX_DELTA, all_calls)):
                if not enabled: continue
                event_map = {}
                for _, contract in frame[frame.option_type.isin([option_type, option_type[0]])].iterrows():
                    try: expiration = date.fromisoformat(str(contract.expiration))
                    except ValueError: continue
                    event_map[str(contract.contract_symbol)] = _event_for_contract(event, today, expiration)
                good, bad = evaluate_contracts(frame, vol.expected_rv, event_map, min_dte=min_dte, max_dte=max_dte, option_type=option_type, target_delta=target, min_delta=lower, max_delta=upper, max_spread=config.MAX_BID_ASK_SPREAD_PCT, min_bid=config.MIN_OPTION_BID)
                if not good.empty: destination.append(good.assign(rv_5=vol.rv_5, rv_20=vol.rv_20, rv_60=vol.rv_60, expected_rv=vol.expected_rv, warnings=" | ".join(WARNINGS)))
                if not bad.empty: rejections.extend(bad.assign(ticker=ticker, rejection_type="contract").to_dict("records"))
        except Exception as exc:
            LOGGER.warning("Skipping %s: %s", ticker, exc)
            rejections.append({"ticker": ticker, "rejection_type": "symbol", "verdict": "REJECTED", "rejection_reason": str(exc)})
    puts = pd.concat(all_puts, ignore_index=True) if all_puts else _empty_frame()
    calls = pd.concat(all_calls, ignore_index=True) if all_calls else _empty_frame()
    if not puts.empty: puts = puts.sort_values("score", ascending=False).groupby("ticker", as_index=False).head(1).sort_values("score", ascending=False)
    if not calls.empty: calls = calls.sort_values("score", ascending=False).groupby("ticker", as_index=False).head(1).sort_values("score", ascending=False)
    return puts.reset_index(drop=True), calls.reset_index(drop=True), pd.DataFrame(rejections)
