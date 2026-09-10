"""Flask web app: search the web and show the five best product picks."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from flask import Flask, jsonify, render_template, request

from config import AppConfig
from main import configure_logging, run as run_pipeline

logger = logging.getLogger(__name__)

app = Flask(__name__)

ALLOWED_CURRENCIES = frozenset(
    {"AED", "USD", "EUR", "GBP", "INR", "SAR", "QAR", "AUD", "CAD"}
)
EXAMPLE_QUERIES = (
    "wireless earbuds under 200 AED",
    "noise cancelling headphones",
    "office chair under 500 AED",
    "mechanical keyboard under $80",
)


def infer_region(query: str, fallback: str) -> str:
    """Pick a DuckDuckGo region from currency/place hints in the query."""
    text = query.lower()
    if re.search(r"\b(aed|dhs|dubai|uae|emirates)\b", text):
        return "ae-en"
    if re.search(r"\b(inr|rupees?|india)\b", text):
        return "in-en"
    if re.search(r"\b(gbp|£|uk|britain)\b", text):
        return "uk-en"
    if re.search(r"\b(eur|€|europe)\b", text):
        return "de-en"
    if re.search(r"\b(usd|\$|usa|united states)\b", text):
        return "us-en"
    return fallback


def web_config(query: str, base_currency: str, max_pages: int) -> AppConfig:
    """Config tuned for the interactive app: broader search, slightly faster scrape."""
    config = AppConfig.from_env()
    config.search_backend = os.getenv("SEARCH_BACKEND", "everywhere")
    config.base_currency = base_currency
    config.max_pages = max_pages
    config.max_results = max(max_pages + 4, 12)
    config.min_delay_s = min(config.min_delay_s, 0.25)
    config.max_delay_s = min(config.max_delay_s, 0.7)
    config.search_region = infer_region(query, config.search_region)
    config.max_retries = 1
    return config


def _card_payload(picks_dict: dict[str, Any]) -> dict[str, Any]:
    """Shape API JSON for the frontend cards."""
    answers = picks_dict.get("answers") or []
    if not answers:
        cats = picks_dict.get("categories") or {}
        answers = [
            {"id": "best_price", "label": "Best price", "blurb": "Lowest price among relevant matches", "item": cats.get("best_price")},
            {"id": "best_overall", "label": "Best match", "blurb": "Strongest mix of relevance, price, and rating", "item": cats.get("best_overall")},
            {"id": "best_value", "label": "Best value", "blurb": "Quality relative to what you pay", "item": cats.get("best_value")},
            {"id": "best_rated", "label": "Best rated", "blurb": "Highest rating among relevant matches", "item": cats.get("best_rated")},
            {"id": "also_consider", "label": "Also consider", "blurb": "Next strongest overall match", "item": cats.get("also_consider")},
        ]
    return {
        "query": picks_dict.get("query"),
        "base_currency": picks_dict.get("base_currency"),
        "items_considered": picks_dict.get("items_considered", 0),
        "notes": picks_dict.get("notes") or [],
        "picks": answers,
        "items": picks_dict.get("items") or [],
    }


@app.get("/")
def index() -> Any:
    return render_template("index.html", examples=EXAMPLE_QUERIES)


@app.get("/api/health")
def health() -> Any:
    return jsonify({"ok": True})


@app.post("/api/search")
def api_search() -> Any:
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query") or request.form.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Please enter a search query."}), 400
    if len(query) > 200:
        return jsonify({"error": "Query is too long (max 200 characters)."}), 400

    currency = str(payload.get("base_currency") or "AED").upper().strip()
    if currency not in ALLOWED_CURRENCIES:
        return jsonify({"error": f"Unsupported currency {currency}."}), 400

    try:
        max_pages = int(payload.get("max_pages") or 8)
    except (TypeError, ValueError):
        max_pages = 6
    max_pages = max(5, min(max_pages, 12))

    config = web_config(query, currency, max_pages)
    logger.info("Web search query=%r currency=%s backend=%s", query, currency, config.search_backend)
    try:
        picks = run_pipeline(query, config)
    except Exception as exc:
        logger.exception("Search failed")
        return jsonify({"error": f"Search failed: {exc.__class__.__name__}"}), 502

    body = _card_payload(picks.to_dict())
    if not picks.items:
        body["error"] = "No usable results. Try a more specific product query."
    return jsonify(body)


def create_app() -> Flask:
    """Factory used by tests and ``flask --app app``."""
    configure_logging(verbose=False)
    return app


if __name__ == "__main__":
    configure_logging(verbose=os.getenv("PRODUCT_FINDER_VERBOSE") == "1")
    port = int(os.getenv("PORT", "5055"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
