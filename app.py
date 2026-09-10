"""Flask web app: search the web and show the five best product picks."""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import Flask, jsonify, render_template, request

from config import AppConfig
from location import apply_country, country_from_headers, get_country, list_countries, resolve_country
from main import configure_logging, run as run_pipeline

logger = logging.getLogger(__name__)

app = Flask(__name__)

ALLOWED_CURRENCIES = frozenset(
    {"AED", "USD", "EUR", "GBP", "INR", "SAR", "QAR", "AUD", "CAD", "KWD", "BHD", "OMR", "EGP", "PKR"}
)


def web_config(
    base_currency: str,
    max_pages: int,
    country_code: str,
) -> AppConfig:
    """Config tuned for the interactive app: broader search, slightly faster scrape."""
    config = AppConfig.from_env()
    config.search_backend = os.getenv("SEARCH_BACKEND", "everywhere")
    config.base_currency = base_currency
    config.max_pages = max_pages
    config.max_results = max(max_pages + 8, 16)
    config.min_delay_s = min(config.min_delay_s, 0.25)
    config.max_delay_s = min(config.max_delay_s, 0.7)
    apply_country(config, country_code)
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
        "country_code": picks_dict.get("country_code"),
        "country_name": picks_dict.get("country_name"),
        "items_considered": picks_dict.get("items_considered", 0),
        "notes": picks_dict.get("notes") or [],
        "picks": answers,
        "items": picks_dict.get("items") or [],
    }


def _header_map() -> dict[str, str]:
    return {str(key): str(value) for key, value in request.headers.items()}


@app.get("/")
def index() -> Any:
    countries = [
        {"code": profile.code, "name": profile.name, "currency": profile.currency}
        for profile in list_countries()
    ]
    examples = get_country("AE").example_queries
    return render_template("index.html", examples=examples, countries=countries)


@app.get("/api/health")
def health() -> Any:
    return jsonify({"ok": True})


@app.get("/api/geo")
def api_geo() -> Any:
    """Suggest a country from CDN geo headers or Accept-Language."""
    geo = country_from_headers(_header_map())
    profile = get_country(geo or os.getenv("PRODUCT_FINDER_COUNTRY") or "AE")
    return jsonify(
        {
            "country": profile.code,
            "name": profile.name,
            "currency": profile.currency,
            "countries": [
                {"code": item.code, "name": item.name, "currency": item.currency}
                for item in list_countries()
            ],
        }
    )


@app.post("/api/search")
def api_search() -> Any:
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query") or request.form.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Please enter a search query."}), 400
    if len(query) > 200:
        return jsonify({"error": "Query is too long (max 200 characters)."}), 400

    explicit_country = str(payload.get("country") or "").strip().upper() or None
    config_probe = AppConfig.from_env()
    profile = resolve_country(
        config_probe,
        query=query,
        explicit=explicit_country,
        headers=_header_map(),
    )

    currency = str(payload.get("base_currency") or profile.currency).upper().strip()
    if currency not in ALLOWED_CURRENCIES:
        return jsonify({"error": f"Unsupported currency {currency}."}), 400

    try:
        max_pages = int(payload.get("max_pages") or 8)
    except (TypeError, ValueError):
        max_pages = 6
    max_pages = max(5, min(max_pages, 12))

    config = web_config(currency, max_pages, profile.code)
    logger.info(
        "Web search query=%r country=%s currency=%s backend=%s",
        query,
        profile.code,
        currency,
        config.search_backend,
    )
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
