# Short Options Scanner

A research-only Python 3.11+ scanner for manually selected cash-secured put and covered-call screening candidates. It never places broker orders and is not financial advice.

## Architecture

`yfinance` supplies daily adjusted closes and realized volatility. `Alpaca` supplies indicative/delayed option bid, ask, IV, and Greeks. `FMP` excludes contracts around earnings. `Gemini` (`gemini-3.6-flash`) formats calculated results into HTML only. `Resend` delivers the optional email.

## Setup

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Fill API keys in `.env`; never commit it. Edit `TICKERS` in `config.py` to define the only symbols scanned.

```bash
python test_run.py
python main.py
```

`test_run.py` is offline by default and writes CSV/JSON examples. The live run requires Alpaca and FMP credentials. Gemini and Resend are optional; CSV/JSON results remain available if email generation or delivery fails.

## Calculations

`RV_L = stdev(log returns over L days) * sqrt(252)` using `ddof=1` and L = 5, 20, 60.

`expected_rv = 0.20 * RV5 + 0.50 * RV20 + 0.30 * RV60`

`expected_move_dollars = spot_price * expected_rv * sqrt(DTE / 252)`

`iv_rv_ratio = implied_volatility / expected_rv`

Bids are the assumed short-sale credit. Midpoint is used only for spread measurement. Candidates are ranked separately by option type using a transparent initial volatility-premium screening score; a positive score is not a probability or profit guarantee.

Earnings are rejected when they occur on/before expiration or within the seven-day configurable buffer. Unverified earnings are rejected conservatively.

## Limitations

Alpaca indicative data may be delayed or stale; check current executable broker quotes before any decision. The model does not account for earnings/news jumps, dividends or ex-dividend early assignment, splits, borrow, taxes, portfolio concentration, or other corporate/regulatory events. Cash-secured puts can result in assignment of 100 shares. Covered calls retain downside stock risk and cap upside above the strike.

## GitHub Actions

The included `.github/workflows/short-options-scanner.yml` runs on weekdays at `20:00 UTC`, which is 12:00 PM Pacific Standard Time. GitHub Actions schedules use UTC and may be delayed. During daylight saving time, `20:00 UTC` is 1:00 PM Pacific Daylight Time. Change the cron expression to `19:00 UTC` during daylight time if a consistent 12:00 PM local-time run is required.

Add these repository secrets under **Settings > Secrets and variables > Actions**:

`ALPACA_API_KEY`, `ALPACA_API_SECRET`, `FMP_API_KEY`, `GEMINI_API_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, and `RESEND_TO_EMAIL`.

The workflow can also be started manually with **Run workflow**. It uploads generated CSV and JSON reports as a workflow artifact for 30 days. Scheduled runs may be delayed, and holidays or early closes need special handling.
