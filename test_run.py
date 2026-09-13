"""Offline-first smoke test; set TEST_SEND_EMAIL=True only when desired."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import json
import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv

import config
from email_report import build_structured_report, generate_email_with_gemini, send_email_with_resend
from events import is_earnings_safe
from options_analysis import evaluate_contracts, normalize_snapshots
from scanner import scan_tickers
from volatility import calculate_volatility

TEST_TICKERS = ["AAPL", "MSFT", "MU", "GOOGL"]
TEST_SEND_EMAIL = True  # Set to True only when you want to test email sending; otherwise, it will skip that step.

def _offline_scan(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Exercise the calculation path for every configured test ticker without API keys."""
    dates = pd.date_range(end=pd.Timestamp.today(), periods=100, freq="B")
    closes = pd.Series(100 * np.exp(np.cumsum(np.full(100, 0.01))), index=dates)
    volatility = calculate_volatility(closes, (config.RV5_WEIGHT, config.RV20_WEIGHT, config.RV60_WEIGHT), range(3, 8))
    today = date.today()
    expiration = today + timedelta(days=5)
    puts: list[pd.DataFrame] = []
    calls: list[pd.DataFrame] = []
    rejected: list[pd.DataFrame] = []
    for ticker in tickers:
        snapshots = [
            {"contract_symbol": f"{ticker}260918P00100000", "option_type": "put", "expiration": expiration.isoformat(), "strike": 95, "bid": 1.20, "ask": 1.25, "implied_volatility": 0.45, "delta": -0.20, "gamma": 0.02, "theta": -0.03, "vega": 0.10},
            {"contract_symbol": f"{ticker}260918C00100000", "option_type": "call", "expiration": expiration.isoformat(), "strike": 105, "bid": 1.10, "ask": 1.15, "implied_volatility": 0.40, "delta": 0.20, "gamma": 0.02, "theta": -0.03, "vega": 0.10},
        ]
        frame = normalize_snapshots(ticker, snapshots, volatility.spot_price, today)
        event = {contract: is_earnings_safe(today, expiration, today + timedelta(days=30), 7) for contract in frame["contract_symbol"]}
        put_results, put_rejected = evaluate_contracts(frame, volatility.expected_rv, event, min_dte=3, max_dte=7, option_type="put", target_delta=-.2, min_delta=-.3, max_delta=-.15, max_spread=.10)
        call_results, call_rejected = evaluate_contracts(frame, volatility.expected_rv, event, min_dte=3, max_dte=7, option_type="call", target_delta=.2, min_delta=.15, max_delta=.30, max_spread=.10)
        if not put_results.empty: puts.append(put_results)
        if not call_results.empty: calls.append(call_results)
        rejected.extend(frame for frame in (put_rejected, call_rejected) if not frame.empty)
    return (
        pd.concat(puts, ignore_index=True) if puts else pd.DataFrame(),
        pd.concat(calls, ignore_index=True) if calls else pd.DataFrame(),
        pd.concat(rejected, ignore_index=True) if rejected else pd.DataFrame(),
    )


def main() -> None:
    load_dotenv()
    tickers = TEST_TICKERS
    live_keys_available = all(os.getenv(name) for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "FMP_API_KEY"))
    if live_keys_available:
        print(f"Running live scanner for test tickers: {', '.join(tickers)}")
        puts, calls, rejected = scan_tickers(tickers, min_dte=3, max_dte=7, scan_puts=True, scan_calls=True)
        mode = "live"
    else:
        print("Alpaca/FMP keys are missing; running offline calculation test for: " + ", ".join(tickers))
        puts, calls, rejected = _offline_scan(tickers)
        mode = "offline"
    report = build_structured_report(puts, calls, rejected, {"mode": mode, "tickers_scanned": tickers, "dte_range": "3-7"})
    output = Path("generated_reports"); output.mkdir(exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    puts.to_csv(output / f"best_puts_{stamp}.csv", index=False); calls.to_csv(output / f"best_calls_{stamp}.csv", index=False); rejected.to_csv(output / f"rejected_{stamp}.csv", index=False); (output / f"report_data_{stamp}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("Scan mode:", mode)
    print("Puts:\n", puts.to_string(index=False) if not puts.empty else "None")
    print("Calls:\n", calls.to_string(index=False) if not calls.empty else "None")
    print("Rejections:\n", rejected.to_string(index=False) if not rejected.empty else "None")
    print("Saved offline report under generated_reports/")

    load_dotenv()
    html, gemini_status = generate_email_with_gemini(report, os.getenv("GEMINI_API_KEY", ""))
    print(gemini_status)
    if TEST_SEND_EMAIL:
        subject = f"Short Options Scanner Test - {date.today()} - Offline Candidates"
        email_result = send_email_with_resend(
            subject,
            html,
            "Offline short-options scanner test report. See the HTML email for details.",
            os.getenv("RESEND_API_KEY", ""),
            os.getenv("RESEND_FROM_EMAIL", ""),
            os.getenv("RESEND_TO_EMAIL", ""),
        )
        print("Email result:", email_result)
    else:
        print("Email sending skipped because TEST_SEND_EMAIL=False.")

if __name__ == "__main__": main()
