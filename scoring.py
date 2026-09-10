"""Transparent scoring and category ranking for scraped product items."""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Optional

from config import AppConfig, ScoreWeights, convert_to_base
from models import ProductItem, RankedPicks, ScoreBreakdown

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "under",
        "below",
        "less",
        "than",
        "best",
        "buy",
        "cheap",
        "price",
        "review",
        "reviews",
    }
)

BUDGET_PATTERN = re.compile(
    r"(?:under|below|less\s+than|upto|up\s+to|<)\s*"
    r"(?P<currency>AED|USD|EUR|GBP|INR|SAR|QAR|Dhs|DH|Rs\.?|\$|€|£|₹)?\s*"
    r"(?P<amount>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?P<currency2>AED|USD|EUR|GBP|INR|SAR|QAR|Dhs|DH|Rs\.?))?",
    re.IGNORECASE,
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, minus a small stopword list."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [word for word in words if word not in STOPWORDS and len(word) > 1]


def extract_budget(query: str) -> Optional[float]:
    """Return a numeric budget mentioned in the query, if any.

    Currency conversion of the budget itself is left to the caller; this returns
    the raw amount as written (e.g. 200 from “under 200 AED”).
    """
    match = BUDGET_PATTERN.search(query)
    if not match:
        return None
    raw = match.group("amount").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def extract_budget_currency(query: str, default: str) -> str:
    match = BUDGET_PATTERN.search(query)
    if not match:
        return default
    token = match.group("currency") or match.group("currency2")
    if not token:
        return default
    aliases = {
        "DHS": "AED",
        "DH": "AED",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "₹": "INR",
        "RS": "INR",
        "RS.": "INR",
    }
    key = token.strip().upper()
    return aliases.get(key, key)


def budget_in_base(query: str, base_currency: str) -> Optional[float]:
    """Parse a query budget and convert it into ``base_currency`` using fixed FX rates."""
    amount = extract_budget(query)
    if amount is None:
        return None
    currency = extract_budget_currency(query, base_currency)
    return convert_to_base(amount, currency, base_currency)


def relevance_score(query: str, item: ProductItem) -> float:
    """0–1 score based on query-term overlap in title, domain, description, and features.

    Title matches weigh more than body matches. An exact phrase hit in the title
    is rewarded so that loosely related pages do not outrank true product pages.
    """
    query_terms = tokenize(query)
    if not query_terms:
        return 0.0

    title = item.title.lower()
    body = " ".join(
        [
            item.description,
            " ".join(item.features),
            item.source_domain.replace(".", " "),
        ]
    ).lower()
    title_tokens = set(tokenize(item.title))
    body_tokens = set(tokenize(body))

    title_hits = sum(1 for term in query_terms if term in title_tokens)
    body_hits = sum(1 for term in query_terms if term in body_tokens)
    phrase = " ".join(query_terms)
    phrase_bonus = 0.15 if phrase and phrase in title else 0.0
    domain_bonus = 0.05 if any(term in item.source_domain.lower() for term in query_terms) else 0.0

    title_part = title_hits / len(query_terms)
    body_part = body_hits / len(query_terms)
    score = 0.70 * title_part + 0.30 * body_part + phrase_bonus + domain_bonus
    return round(min(1.0, score), 4)


def _log_price_score(amount: float, lo: float, hi: float) -> float:
    """Lower prices score higher; log scale reduces the advantage of ultra-cheap outliers."""
    if hi <= lo:
        return 1.0
    span = math.log(hi) - math.log(lo)
    if span <= 0:
        return 1.0
    return 1.0 - (math.log(amount) - math.log(lo)) / span


def apply_scores(
    items: list[ProductItem],
    query: str,
    config: AppConfig,
    weights: ScoreWeights | None = None,
) -> list[ProductItem]:
    """Fill ``item.scores`` for every product using the current catalogue as context."""
    weights = (weights or config.weights).normalized()
    budget = budget_in_base(query, config.base_currency)

    known_prices = [item.price_base for item in items if item.price_base and item.price_base > 0]
    if known_prices:
        lo = min(known_prices)
        hi = max(known_prices)
        # Widen a zero-span set so a single known price still gets a mid-high score.
        if hi == lo:
            lo = max(lo * 0.5, 0.01)
            hi = hi * 1.5
        mid = median(known_prices)
    else:
        lo = hi = mid = 1.0

    for item in items:
        rel = relevance_score(query, item)

        if item.price_base and item.price_base > 0:
            price_s = _log_price_score(max(item.price_base, 0.01), max(lo, 0.01), hi)
            if budget is not None and item.price_base > budget:
                # Over-budget items keep a price but lose some of the cheapness bonus.
                overshoot = min(1.0, (item.price_base - budget) / max(budget, 1.0))
                price_s *= max(0.15, 1.0 - 0.6 * overshoot)
        else:
            price_s = config.missing_price_score

        if item.rating is None:
            item.rating = config.default_rating
            item.rating_is_default = True
        rating_s = min(1.0, max(0.0, item.rating / config.rating_scale))
        if item.review_count:
            # Light confidence bump for well-reviewed items; missing counts stay neutral.
            rating_s = min(1.0, rating_s * (1.0 + min(0.08, math.log10(1 + item.review_count) / 40)))

        overall = (
            weights.relevance * rel
            + weights.price * price_s
            + weights.rating * rating_s
        )

        # Best value: quality per unit of (log) price. Unknown prices get a low value score.
        quality = 0.55 * rel + 0.45 * rating_s
        if item.price_base and item.price_base > 0:
            unit = 1.0 + math.log1p(item.price_base / max(mid, 1.0))
            value = quality / unit
        else:
            value = quality * 0.25

        item.scores = ScoreBreakdown(
            relevance=round(rel, 4),
            price=round(price_s, 4),
            rating=round(rating_s, 4),
            overall=round(overall, 4),
            value=round(value, 4),
        )
    return items


def rank_items(
    items: list[ProductItem],
    query: str,
    config: AppConfig,
    weights: ScoreWeights | None = None,
) -> RankedPicks:
    """Score items and pick Best price, Best overall match, and Best value.

    Categories are independent, so one product may win more than one of them.
    That keeps “Best price” honest even when the cheapest item is also the
    strongest overall match.
    """
    weights = (weights or config.weights).normalized()
    scored = apply_scores(items, query, config, weights)
    notes: list[str] = []

    priced_relevant = [
        item
        for item in scored
        if item.price_base is not None
        and item.scores.relevance >= config.min_relevance_for_price
    ]
    if not priced_relevant:
        notes.append(
            "No priced items met the relevance threshold; Best price uses the lowest "
            "known price among all results."
        )
        priced_relevant = [item for item in scored if item.price_base is not None]

    value_pool = [
        item
        for item in scored
        if item.price_base is not None
        and item.scores.relevance >= config.min_relevance_for_value
    ]
    if not value_pool:
        value_pool = [item for item in scored if item.price_base is not None]

    overall_sorted = sorted(scored, key=lambda i: i.scores.overall, reverse=True)
    price_sorted = sorted(priced_relevant, key=lambda i: (i.price_base or math.inf, -i.scores.overall))
    value_sorted = sorted(value_pool, key=lambda i: i.scores.value, reverse=True)

    best_overall = overall_sorted[0] if overall_sorted else None
    best_price = price_sorted[0] if price_sorted else None
    best_value = value_sorted[0] if value_sorted else None

    if best_price is None:
        notes.append("No prices could be parsed; Best price is empty.")
    if best_value is None:
        notes.append("No priced items available for Best value.")
    if not scored:
        notes.append("No search results were scraped.")

    return RankedPicks(
        query=query,
        base_currency=config.base_currency,
        items=sorted(scored, key=lambda i: i.scores.overall, reverse=True),
        best_price=best_price,
        best_overall=best_overall,
        best_value=best_value,
        weights={
            "relevance": weights.relevance,
            "price": weights.price,
            "rating": weights.rating,
        },
        notes=notes,
    )
