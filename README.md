# OptionsPremium Scanner

A short-options scanner that evaluates near-term (1–7 DTE) cash-secured puts and covered calls. The scanner is intended to identify options contracts that are "expensive" while filtering for low liquidity or nearby earnings events.

<img width="589" height="557" alt="image" src="https://github.com/user-attachments/assets/9d313153-7bb2-4ee5-96e3-ddb9cd73c766" />

## Features

- Scans short-dated puts and calls
- Pulls options chain and Greeks using Alpaca API
- Calculates 5, 20, and 60-day realized volatility
- Estimates expected move using weighted realized volatility (`RV5_WEIGHT = 0.20`, `RV20_WEIGHT = 0.50`, `RV60_WEIGHT = 0.30`)
- Filters contracts by delta and wide bid-ask spreads
- Uses Gemini API to organize `.csv` data
- Generates automated email delivery using Resend API
- Supports automated execution through GitHub Actions

## Scoring

The scanner determines if the contracts are favorable by the following factors:

```text
50%  Implied volatility relative to realized volatility
25%  Premium yield
15%  Distance from expected move
10%  Bid-ask spread penalty
```

## Configuration

The `config.py` file can be edited to adjust screening thresholds and interested tickers.

## Project Structure

```text
OptionsPremiumScanner
│
├── .github/
│   └── workflows/          # GitHub Actions automation
│
├── config.py               # Scanner settings and thresholds
├── email_report.py         # HTML/Gemini email report generation
├── events.py               # Earnings-calendar checks
├── main.py                 # Main application entry point
├── options_analysis.py     # Contract normalization and scoring
├── scanner.py              # Option-chain scanning pipeline
├── volatility.py           # Realized volatility calculations
├── requirements.txt        # Python dependencies
└── .gitignore
```

## Future Improvements

- Backtesting historical scanner results
- Performance tracking for previously saved contracts
- Expanded strategy options

## Requirements

- Python 3
- Alpaca API credentials
- Financial Modeling Prep API key

Optional:

- Gemini API key
- Resend API key

### Install Dependencies

```bash
pip install -r requirements.txt
```

Main dependencies include:

```text
yfinance
pandas
numpy
requests
python-dotenv
alpaca-py
google-genai
resend
pytest
```

## Environment Variables

The scanner requires the following environment variables:

```text
ALPACA_API_KEY
ALPACA_API_SECRET
FMP_API_KEY
```

Optional email/report variables:

```text
GEMINI_API_KEY
RESEND_API_KEY
RESEND_FROM_EMAIL
RESEND_TO_EMAIL
```

Create a `.env` file in the project directory and add your credentials.

Example:

```env
ALPACA_API_KEY=your_key
ALPACA_API_SECRET=your_secret
FMP_API_KEY=your_key

GEMINI_API_KEY=your_key
RESEND_API_KEY=your_key
RESEND_FROM_EMAIL=your_email
RESEND_TO_EMAIL=destination_email
```

## Running the Scanner

Clone the repository:

```bash
git clone https://github.com/DerenDesign/OptionsPremiumScanner.git
cd OptionsPremiumScanner
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the scanner:

```bash
python main.py
```
