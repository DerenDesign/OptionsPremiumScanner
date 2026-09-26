from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
_CACHE: dict[tuple[str, str, str, str], dict[str, Any]] = {}


def get_next_earnings_date(symbol: str, start_date: date, end_date: date, fmp_api_key: str) -> dict[str, Any]:
    key = (symbol.upper(), start_date.isoformat(), end_date.isoformat(), fmp_api_key)
    if key in _CACHE:
        return _CACHE[key]
    if not fmp_api_key:
        result = {"earnings_date": None, "earnings_time": None, "days_until_earnings": None, "safe": False, "reason": "REJECTED: FMP_API_KEY is missing; earnings cannot be verified."}
        _CACHE[key] = result
        return result
    url = "https://financialmodelingprep.com/stable/earnings-calendar"
    try:
        response = requests.get(url, params={"from": start_date.isoformat(), "to": end_date.isoformat(), "apikey": fmp_api_key}, timeout=15)
        if response.status_code == 429:
            time.sleep(1)
        response.raise_for_status()
        rows = response.json()
        rows = rows if isinstance(rows, list) else []
        matching = [row for row in rows if str(row.get("symbol", row.get("ticker", ""))).upper() == symbol.upper()]
        if not matching:
            result = {"earnings_date": None, "earnings_time": None, "days_until_earnings": None, "safe": False, "reason": "REJECTED: FMP returned no verifiable upcoming earnings date."}
        else:
            row = sorted(matching, key=lambda item: str(item.get("date", "9999-12-31")))[0]
            earnings_date = date.fromisoformat(str(row["date"])[:10])
            result = {"earnings_date": earnings_date.isoformat(), "earnings_time": row.get("time") or row.get("epsEstimatedTime"), "days_until_earnings": (earnings_date - start_date).days, "safe": True, "reason": "Earnings date retrieved; contract expiration still requires filtering."}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        LOGGER.warning("FMP request failed for %s: %s", symbol, exc)
        result = {"earnings_date": None, "earnings_time": None, "days_until_earnings": None, "safe": False, "reason": f"REJECTED: earnings verification failed ({type(exc).__name__})."}
    _CACHE[key] = result
    return result


def is_earnings_safe(today: date, expiration: date, earnings_date: date | None, earnings_buffer_days: int = 7) -> dict[str, Any]:
    if earnings_date is None:
        return {"earnings_date": None, "earnings_time": None, "days_until_earnings": None, "safe": False, "reason": "REJECTED: earnings date is unverified."}
    days = (earnings_date - today).days
    
    if earnings_date <= expiration:
        return {"earnings_date": earnings_date.isoformat(), "days_until_earnings": days, "safe": False, "reason": f"REJECTED: Earnings on {earnings_date} is before/on expiration {expiration}."}
    
    if days <= earnings_buffer_days:
        return {"earnings_date": earnings_date.isoformat(), "days_until_earnings": days, "safe": False, "reason": f"REJECTED: Earnings is only {days} days away; required buffer is {earnings_buffer_days} days."}
    
    return {"earnings_date": earnings_date.isoformat(), "days_until_earnings": days, "safe": True, "reason": "PASS: earnings is outside the exclusion window."}
