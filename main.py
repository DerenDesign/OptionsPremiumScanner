from __future__ import annotations

from datetime import datetime
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd

import config
from email_report import build_structured_report, generate_email_with_gemini, send_email_with_resend
from scanner import scan_tickers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def _save(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)

def main() -> int:
    load_dotenv()
    missing = [name for name in ("ALPACA_API_KEY", "ALPACA_API_SECRET", "FMP_API_KEY") if not os.getenv(name)]
    if missing:
        print("Missing required live-scan environment variables: " + ", ".join(missing) + ". Copy .env.example to .env and fill them in.")
        return 1
    puts, calls, rejected = scan_tickers(config.TICKERS, config.MIN_DTE, config.MAX_DTE, config.SCAN_PUTS, config.SCAN_CALLS)
    output = Path("generated_reports"); output.mkdir(exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    _save(puts, output / f"best_puts_{stamp}.csv"); _save(calls, output / f"best_calls_{stamp}.csv"); _save(rejected, output / f"rejected_{stamp}.csv")
    report = build_structured_report(puts, calls, rejected, {"tickers_scanned": config.TICKERS, "min_dte": config.MIN_DTE, "max_dte": config.MAX_DTE})
    (output / f"report_data_{stamp}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Tickers scanned: {len(config.TICKERS)} | earnings/other rejections: {len(rejected)} | puts: {len(puts)} | calls: {len(calls)}")
    print("Top puts:\n", puts.head(5).to_string(index=False) if not puts.empty else "None")
    print("Top calls:\n", calls.head(5).to_string(index=False) if not calls.empty else "None")
    html, note = generate_email_with_gemini(report, os.getenv("GEMINI_API_KEY", ""))
    subject = f"Short Options Scanner — {datetime.now().date()} — Top 1–7 DTE Candidates"
    result = send_email_with_resend(subject, html, "See HTML report.", os.getenv("RESEND_API_KEY", ""), os.getenv("RESEND_FROM_EMAIL", ""), os.getenv("RESEND_TO_EMAIL", ""))
    print(note); print(f"Email: {result.get('status')} {result.get('reason', '')}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
