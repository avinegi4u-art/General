"""Runtime configuration: timeouts, scoring weights, FX rates, and env overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


DEFAULT_USER_AGENTS: tuple[str, ...] = (
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.2 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
)

# Approximate mid-market rates used to normalize prices into a base currency.
# Values are "1 unit of currency = N AED". No live FX feed is required.
FX_TO_AED: dict[str, float] = {
    "AED": 1.0,
    "USD": 3.67,
    "EUR": 4.00,
    "GBP": 4.70,
    "INR": 0.044,
    "SAR": 0.98,
    "QAR": 1.01,
    "KWD": 12.00,
    "BHD": 9.75,
    "OMR": 9.54,
    "EGP": 0.075,
    "PKR": 0.013,
    "CAD": 2.70,
    "AUD": 2.40,
    "JPY": 0.025,
    "CNY": 0.51,
    "CHF": 4.15,
}

SKIP_DOMAINS: frozenset[str] = frozenset(
    {
        "google.com",
        "google.ae",
        "google.co.uk",
        "google.co.in",
        "bing.com",
        "duckduckgo.com",
        "yahoo.com",
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "tiktok.com",
        "pinterest.com",
        "linkedin.com",
        "reddit.com",
        "wikipedia.org",
        "glarity.app",
        "perplexity.ai",
        "chatgpt.com",
        "openai.com",
    }
)

SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4", ".zip"}
)

PRODUCT_PATH_HINTS: tuple[str, ...] = (
    "/dp/",
    "/gp/product",
    "/p/",
    "/product",
    "/prd/",
    "/pd/",
    "/ip/",
    "/itm",
    "/item",
    "/products/",
)

# Drop extracted amounts that are almost certainly years, ratings, or shipping crumbs.
PLAUSIBLE_PRICE_RANGE: dict[str, tuple[float, float]] = {
    "AED": (15.0, 200_000.0),
    "USD": (5.0, 100_000.0),
    "EUR": (5.0, 100_000.0),
    "GBP": (5.0, 100_000.0),
    "INR": (99.0, 2_000_000.0),
    "SAR": (15.0, 200_000.0),
    "QAR": (15.0, 200_000.0),
    "AUD": (5.0, 100_000.0),
    "CAD": (5.0, 100_000.0),
}


@dataclass(frozen=True)
class ScoreWeights:
    """Relative importance of each scoring component. Values are normalized to sum to 1."""

    relevance: float = 0.38
    price: float = 0.20
    rating: float = 0.22
    availability: float = 0.20

    def normalized(self) -> "ScoreWeights":
        total = self.relevance + self.price + self.rating + self.availability
        if total <= 0:
            return ScoreWeights()
        return ScoreWeights(
            relevance=self.relevance / total,
            price=self.price / total,
            rating=self.rating / total,
            availability=self.availability / total,
        )


@dataclass
class AppConfig:
    """Central settings loaded from defaults, environment variables, and CLI flags."""

    request_timeout: float = 12.0
    max_retries: int = 2
    min_delay_s: float = 0.4
    max_delay_s: float = 1.2
    max_results: int = 12
    max_pages: int = 10
    base_currency: str = "AED"
    country_code: str = "AE"
    search_backend: str = "duckduckgo"
    search_region: str = "ae-en"
    google_gl: str = "ae"
    google_hl: str = "en"
    google_location: str = "United Arab Emirates"
    user_agents: tuple[str, ...] = DEFAULT_USER_AGENTS
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    missing_price_score: float = 0.20
    default_rating: float = 3.5
    rating_scale: float = 5.0
    min_relevance_for_price: float = 0.40
    min_relevance_for_value: float = 0.35
    top_answers: int = 5
    serpapi_url: str = "https://serpapi.com/search.json"
    google_cse_url: str = "https://www.googleapis.com/customsearch/v1"

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Build config from environment variables, falling back to defaults."""
        cfg = cls()
        cfg.request_timeout = float(os.getenv("PRODUCT_FINDER_TIMEOUT", cfg.request_timeout))
        cfg.max_retries = int(os.getenv("PRODUCT_FINDER_MAX_RETRIES", cfg.max_retries))
        cfg.min_delay_s = float(os.getenv("PRODUCT_FINDER_MIN_DELAY", cfg.min_delay_s))
        cfg.max_delay_s = float(os.getenv("PRODUCT_FINDER_MAX_DELAY", cfg.max_delay_s))
        cfg.max_results = int(os.getenv("PRODUCT_FINDER_MAX_RESULTS", cfg.max_results))
        cfg.max_pages = int(os.getenv("PRODUCT_FINDER_MAX_PAGES", cfg.max_pages))
        cfg.base_currency = os.getenv("PRODUCT_FINDER_BASE_CURRENCY", cfg.base_currency).upper()
        cfg.country_code = os.getenv("PRODUCT_FINDER_COUNTRY", cfg.country_code).upper()
        cfg.search_backend = os.getenv("SEARCH_BACKEND", cfg.search_backend).lower()
        cfg.search_region = os.getenv("SEARCH_REGION", cfg.search_region)
        cfg.default_rating = float(os.getenv("PRODUCT_FINDER_DEFAULT_RATING", cfg.default_rating))
        cfg.min_relevance_for_price = float(
            os.getenv("PRODUCT_FINDER_MIN_RELEVANCE_PRICE", cfg.min_relevance_for_price)
        )
        cfg.min_relevance_for_value = float(
            os.getenv("PRODUCT_FINDER_MIN_RELEVANCE_VALUE", cfg.min_relevance_for_value)
        )

        weights_json = os.getenv("PRODUCT_FINDER_WEIGHTS")
        if weights_json:
            cfg.weights = parse_weights(weights_json)
        else:
            cfg.weights = ScoreWeights(
                relevance=float(os.getenv("SCORE_WEIGHT_RELEVANCE", cfg.weights.relevance)),
                price=float(os.getenv("SCORE_WEIGHT_PRICE", cfg.weights.price)),
                rating=float(os.getenv("SCORE_WEIGHT_RATING", cfg.weights.rating)),
                availability=float(os.getenv("SCORE_WEIGHT_AVAILABILITY", cfg.weights.availability)),
            ).normalized()
        return cfg


def parse_weights(raw: str | dict[str, Any]) -> ScoreWeights:
    """Parse a JSON object or dict of scoring weights and normalize them."""
    data: dict[str, Any]
    if isinstance(raw, str):
        data = json.loads(raw)
    else:
        data = raw
    weights = ScoreWeights(
        relevance=float(data.get("relevance", 0.38)),
        price=float(data.get("price", 0.20)),
        rating=float(data.get("rating", 0.22)),
        availability=float(data.get("availability", 0.0)),
    )
    return weights.normalized()


def convert_to_base(amount: float, currency: str, base_currency: str) -> float:
    """Convert ``amount`` from ``currency`` into ``base_currency`` via AED.

    Unknown currencies are treated as already being in the base currency.
    """
    src = currency.upper()
    dst = base_currency.upper()
    src_rate = FX_TO_AED.get(src)
    dst_rate = FX_TO_AED.get(dst)
    if src_rate is None or dst_rate is None or dst_rate == 0:
        return amount
    amount_in_aed = amount * src_rate
    return amount_in_aed / dst_rate
