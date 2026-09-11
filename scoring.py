"""Transparent scoring and category ranking for scraped product items."""

from __future__ import annotations

import math
from statistics import median
from typing import Optional

from config import AppConfig, ScoreWeights
from intent import (
    build_overview,
    popular_model_bonus,
    price_outside_band,
    spec_collides_with_budget,
)
from location import classify_listing, get_country, is_buyable
from models import LabeledPick, ProductItem, RankedPicks, ScoreBreakdown
from querying import (
    accessory_multiplier,
    budget_in_base,
    category_matches,
    expand_shopper_query,
    is_modelish_term,
    missing_hard_required,
    missing_required,
    query_match_terms,
    required_terms,
    tokenize,
)
from search import looks_like_category_url


def relevance_score(query: str, item: ProductItem, base_currency: str = "AED") -> float:
    """0–1 score based on query-term overlap, with brand/model required.

    Title matches weigh more than body matches. Spare parts (“compatible with
    VSETT 10+”, mudguards, kits) score near zero unless the query asks for a part.
    Brand and model tokens such as ``vsett`` and ``10+`` must appear or the score
    is capped so they cannot win Best price.
    """
    query_terms = query_match_terms(query)
    if not query_terms:
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
    req = required_terms(query)
    if len(req) >= 2 and " ".join(req[:2]) in title:
        phrase_bonus = max(phrase_bonus, 0.2)
    elif req and req[0] in title and any(term.endswith("+") and term in title_tokens for term in req):
        phrase_bonus = max(phrase_bonus, 0.18)
    domain_bonus = 0.05 if any(term in item.source_domain.lower() for term in query_terms) else 0.0

    title_part = title_hits / len(query_terms)
    body_part = body_hits / len(query_terms)
    score = 0.70 * title_part + 0.30 * body_part + phrase_bonus + domain_bonus

    blob = f"{item.title} {item.url}"
    hard_missing = missing_hard_required(query, blob)
    soft_missing = [
        term
        for term in missing_required(query, f"{item.title} {item.description} {item.url}")
        if is_modelish_term(term)
    ]
    if hard_missing:
        # Brand missing from the listing: this is not the product they asked for.
        score = min(score, 0.18) * 0.4
    elif soft_missing:
        # Amazon.ae often titles “NAVEE Electric Scooter” without “GT3” in the slug.
        score = min(score, 0.48)

    score *= accessory_multiplier(query, item.title)
    blob = f"{item.title} {item.description}"
    if not category_matches(query, blob):
        # Washers, resistors, 10K gold, motorcycle thermometers, etc.
        score = min(score, 0.14) * 0.3
    elif spec_collides_with_budget(query, blob):
        # “10000W scooter” is not a 10000 AED budget match.
        score = min(score, 0.16) * 0.35
    elif looks_like_category_url(item.url):
        # A shop index is not a product to buy.
        score *= 0.4
    else:
        score = min(1.0, score + popular_model_bonus(query, item.title))
    if (
        item.price_base
        and item.price_base > 0
        and price_outside_band(query, item.price_base, base_currency)
    ):
        # Category crumbs (AED 25 “electric scooters”) cannot win Best price.
        score = min(score, 0.22)
    return round(min(1.0, max(0.0, score)), 4)


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
    country = get_country(config.country_code)

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
        listing = classify_listing(item.url, item.source_domain, country)
        item.availability = listing.kind
        item.availability_label = listing.label
        avail_s = listing.score

        rel = relevance_score(query, item, config.base_currency)

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
            + weights.availability * avail_s
        )

        # Best value: quality per unit of (log) price. Unknown prices get a low value score.
        # Local / ships-here listings keep more of their value score than foreign storefronts.
        quality = 0.55 * rel + 0.45 * rating_s
        if item.price_base and item.price_base > 0:
            unit = 1.0 + math.log1p(item.price_base / max(mid, 1.0))
            value = quality / unit
        else:
            value = quality * 0.25
        value *= 0.55 + 0.45 * avail_s

        item.scores = ScoreBreakdown(
            relevance=round(rel, 4),
            price=round(price_s, 4),
            rating=round(rating_s, 4),
            availability=round(avail_s, 4),
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
    """Score items and return the top answers (default five).

    Category winners (price / match / value / rated) are chosen independently so
    “Best price” stays the cheapest relevant listing. The displayed answer list
    then prefers distinct URLs, filling leftover slots from the overall ranking.
    """
    weights = (weights or config.weights).normalized()
    scored = apply_scores(items, query, config, weights)
    notes: list[str] = []
    country = get_country(config.country_code)

    # Match the product first; only then prefer local / ships-to-you storefronts.
    on_query = [
        item for item in scored if item.scores.relevance >= config.min_relevance_for_value
    ]
    off_query = len(scored) - len(on_query)
    if on_query:
        if off_query:
            notes.append(
                f"Hid {off_query} listing(s) that were spare parts or did not match "
                "the product name you typed."
            )
        pool = on_query
    else:
        notes.append(
            "No listing closely matched the product you asked for; spare parts and "
            "lookalikes were skipped."
        )
        pool = []

    preferred = [item for item in pool if is_buyable(item.availability)]
    unknown = [item for item in pool if item.availability == "unknown"]
    if preferred:
        foreign_dropped = len(pool) - len(preferred)
        in_band = [
            item
            for item in preferred
            if not item.price_base
            or not price_outside_band(query, item.price_base, config.base_currency)
        ]
        if in_band and len(in_band) < len(preferred):
            notes.append(
                "Hid listings whose prices were far outside a buyable range for this product."
            )
            preferred = in_band
        catalogue = preferred
        if foreign_dropped:
            notes.append(
                f"Hid {foreign_dropped} listing(s) from other countries that may not ship to "
                f"{country.name}. Showing stores in {country.name} and sellers that "
                f"deliver there (for example AliExpress)."
            )
    elif unknown:
        catalogue = unknown
        foreign_n = sum(1 for item in pool if item.availability == "foreign")
        if foreign_n:
            notes.append(
                f"Few local or deliverable listings were found for {country.name}; "
                "other-country storefronts were still excluded from the top picks."
            )
    else:
        catalogue = []
        if pool:
            notes.append(
                f"Found listings only from other countries that may not ship to "
                f"{country.name}; they were left out of the top picks."
            )

    priced_relevant = [
        item
        for item in catalogue
        if item.price_base is not None
        and item.scores.relevance >= config.min_relevance_for_price
    ]
    budget = budget_in_base(query, config.base_currency)
    if budget is not None:
        in_budget = [item for item in priced_relevant if (item.price_base or 0) <= budget]
        if in_budget:
            priced_relevant = in_budget
        elif priced_relevant:
            notes.append(
                f"No priced match was at or under {int(budget)} {config.base_currency}."
            )
    if not priced_relevant:
        notes.append(
            "No priced items were a close enough match to the query; Best price is empty "
            "rather than falling back to a cheap unrelated listing."
        )

    value_pool = [
        item
        for item in catalogue
        if item.price_base is not None
        and item.scores.relevance >= config.min_relevance_for_value
    ]
    if not value_pool:
        notes.append("No priced items available for Best value.")

    rated_pool = [
        item
        for item in catalogue
        if item.scores.relevance >= config.min_relevance_for_value
    ]

    overall_sorted = sorted(catalogue, key=lambda i: i.scores.overall, reverse=True)
    price_sorted = sorted(priced_relevant, key=lambda i: (i.price_base or math.inf, -i.scores.overall))
    value_sorted = sorted(value_pool, key=lambda i: i.scores.value, reverse=True)
    rated_sorted = sorted(
        rated_pool,
        key=lambda i: (
            i.rating_is_default,
            -(i.rating or 0.0),
            -(i.review_count or 0),
            -i.scores.overall,
        ),
    )

    best_overall = overall_sorted[0] if overall_sorted else None
    best_price = price_sorted[0] if price_sorted else None
    best_value = value_sorted[0] if value_sorted else None
    best_rated = rated_sorted[0] if rated_sorted else None

    if best_price is None:
        notes.append("No prices could be parsed; Best price is empty.")
    if best_value is None:
        notes.append("No priced items available for Best value.")
    if not scored:
        notes.append("No search results were scraped.")
    notes.insert(
        0,
        f"Ranked for {country.name}: local stores first, then sellers that ship there.",
    )
    interpreted = expand_shopper_query(query)
    if interpreted.lower() != " ".join(query.lower().split()):
        notes.insert(0, f"Interpreted as {interpreted}.")

    answers = _build_answers(
        limit=config.top_answers,
        overall_sorted=overall_sorted,
        price_sorted=price_sorted,
        value_sorted=value_sorted,
        rated_sorted=rated_sorted,
    )
    also_consider = next((pick.item for pick in answers if pick.key.startswith("also")), None)
    overview = build_overview(query, country.name, config.base_currency, answers)

    return RankedPicks(
        query=query,
        base_currency=config.base_currency,
        country_code=country.code,
        country_name=country.name,
        items=overall_sorted,
        best_price=best_price,
        best_overall=best_overall,
        best_value=best_value,
        best_rated=best_rated,
        also_consider=also_consider,
        answers=answers,
        overview=overview,
        weights={
            "relevance": weights.relevance,
            "price": weights.price,
            "rating": weights.rating,
            "availability": weights.availability,
        },
        notes=notes,
    )


def _build_answers(
    limit: int,
    overall_sorted: list[ProductItem],
    price_sorted: list[ProductItem],
    value_sorted: list[ProductItem],
    rated_sorted: list[ProductItem],
) -> list[LabeledPick]:
    """Build up to ``limit`` distinct answers, one per category then fillers."""
    used: set[str] = set()
    answers: list[LabeledPick] = []

    def first_unused(pool: list[ProductItem]) -> Optional[ProductItem]:
        for item in pool:
            if item.url not in used:
                return item
        return None

    def add(key: str, label: str, blurb: str, item: Optional[ProductItem]) -> None:
        if item is None or item.url in used or len(answers) >= limit:
            return
        used.add(item.url)
        answers.append(LabeledPick(key=key, label=label, blurb=blurb, item=item))

    add("best_overall", "Best match", "Strongest mix of relevance, price, and rating", first_unused(overall_sorted))
    add("best_price", "Best price", "Lowest price among relevant matches", first_unused(price_sorted))
    add("best_value", "Best value", "Quality relative to what you pay", first_unused(value_sorted))
    add("best_rated", "Best rated", "Highest rating among relevant matches", first_unused(rated_sorted))

    extra_n = 1
    for item in overall_sorted:
        if len(answers) >= limit:
            break
        add(f"also_consider_{extra_n}", "Also consider", "Next strongest overall match", item)
        extra_n += 1
    return answers
