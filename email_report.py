from __future__ import annotations

from datetime import datetime
import json
from typing import Any

import pandas as pd

import config

DISCLAIMER = "Research screening only -- not financial advice or an instruction to trade."

def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty: return []
    clean = frame.head(config.TOP_N_EMAIL_RESULTS).copy().replace({float("nan"): None})
    return json.loads(clean.to_json(orient="records", date_format="iso"))

def build_structured_report(best_puts: pd.DataFrame, best_calls: pd.DataFrame, rejected: pd.DataFrame, run_metadata: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": datetime.now().astimezone().isoformat(), "run_metadata": run_metadata, "disclaimer": DISCLAIMER, "score_meaning": "A transparent relative screening score: 50% IV/RV, 25% premium yield, 15% distance from expected move, minus 10% bid-ask spread. Higher is better only when comparing same-type contracts in this scan; it is not a probability, expected return, or guarantee of profit.", "rejection_count": len(rejected), "top_cash_secured_puts": _records(best_puts), "top_covered_calls": _records(best_calls)}

def _fallback_html(report: dict[str, Any]) -> str:
    def table(title: str, rows: list[dict[str, Any]]) -> str:
        items = "".join(f"<li><b>{r.get('ticker')}</b> stock ${r.get('current_stock_price')}, {r.get('expiration')} DTE {r.get('dte')}, strike {r.get('strike')}, option price/sale credit ${r.get('option_price')}, IV/RV {r.get('iv_rv_ratio')}, score {r.get('score')}<br><b>Why it passed:</b> {r.get('why_screened')}</li>" for r in rows)
        return f"<h2>{title}</h2><ul>{items or '<li>None</li>'}</ul>"
    return f"<html><body><h1>Short Options Scanner</h1><p><b>Score meaning:</b> {report['score_meaning']}</p>{table('Top cash-secured puts', report['top_cash_secured_puts'])}{table('Top covered calls', report['top_covered_calls'])}<p>{report['disclaimer']}</p></body></html>"

def generate_email_with_gemini(structured_report: dict[str, Any], gemini_api_key: str) -> tuple[str, str]:
    fallback = _fallback_html(structured_report)
    if not gemini_api_key: return fallback, "Gemini key missing; deterministic fallback used."
    prompt = """Create a concise professional HTML email from ONLY this JSON. Do not invent data, calculate anything, or make investment recommendations. Call items screening candidates, not trades to execute. Show current_stock_price from yfinance. Explain that option_price is the bid and is the assumed sale credit, not a midpoint or guaranteed fill. Include why_screened for each item. Explain score_meaning exactly as supplied. Include separate sections for top cash-secured puts and top covered calls, and relevant fields: ticker, current stock price, expiration, DTE, strike, option price, bid, ask, IV, expected RV, IV/RV, delta, expected move, effective purchase/call-away price, score, and earnings status. Mention that quotes may be delayed. Return HTML only.\n\nJSON:\n""" + json.dumps(structured_report, default=str)
    try:
        from google import genai
        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(model=config.GEMINI_MODEL, contents=prompt)
        html = (response.text or "").strip()
        return (html or fallback), "Gemini generated email."
    except Exception as exc:
        return fallback, f"Gemini failed; deterministic fallback used: {type(exc).__name__}"

def send_email_with_resend(subject: str, html: str, text: str, resend_api_key: str, from_email: str, to_email: str) -> dict[str, Any]:
    missing = [name for name, value in (("RESEND_API_KEY", resend_api_key), ("RESEND_FROM_EMAIL", from_email), ("RESEND_TO_EMAIL", to_email)) if not value or not value.strip()]
    if missing:
        return {"ok": False, "status": "not_sent", "reason": "Resend email configuration is incomplete: missing " + ", ".join(missing) + "."}
    try:
        import resend
        resend.api_key = resend_api_key
        result = resend.Emails.send({"from": from_email, "to": [to_email], "subject": subject, "html": html, "text": text})
        return {"ok": True, "status": "sent", "id": result.get("id") if isinstance(result, dict) else str(result)}
    except Exception as exc:
        return {"ok": False, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
