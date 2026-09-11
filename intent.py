"""Query understanding: what the shopper meant, not the tokens they typed.

Google’s original insight was ranking by meaning. FindBest does the shopping
version: expand shorthand, detect the product type, keep the budget as money
(not 10k-ohm / 10K gold / 10000W), and write a short overview of the picks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from config import convert_to_base
from querying import (
    budget_in_base,
    expand_shopper_query,
    extract_budget,
    extract_budget_currency,
    query_match_terms,
    required_terms,
    wants_electric_scooter,
)


@dataclass(frozen=True)
class CategoryProfile:
    """A shoppable product type with a sane price band (AED) and known models."""

    key: str
    phrase: str
    price_aed: tuple[float, float]
    popular: tuple[str, ...] = ()


CATEGORIES: tuple[CategoryProfile, ...] = (
    CategoryProfile(
        key="electric_scooter",
        phrase="electric scooter",
        price_aed=(400.0, 18000.0),
        popular=(
            "Xiaomi Electric Scooter 6 Pro",
            "Xiaomi Electric Scooter 6 Max",
            "Xiaomi Electric Scooter 6 Ultra",
            "Xiaomi Electric Scooter 4 Ultra",
            "CRONY M365 MAX Electric Scooter",
            "Segway Ninebot Max G30",
            "Kugoo Kirin Electric Scooter",
        ),
    ),
    CategoryProfile(
        key="earbuds",
        phrase="wireless earbuds",
        price_aed=(25.0, 2500.0),
        popular=("Sony WF-1000XM5", "Samsung Galaxy Buds", "Apple AirPods Pro"),
    ),
    CategoryProfile(
        key="headphones",
        phrase="headphones",
        price_aed=(40.0, 4000.0),
        popular=("Sony WH-1000XM5", "Bose QuietComfort", "Apple AirPods Max"),
    ),
    CategoryProfile(
        key="office_chair",
        phrase="office chair",
        price_aed=(80.0, 5000.0),
    ),
)


@dataclass
class QueryIntent:
    """Normalized shopping intent used for search, filters, and the overview."""

    original: str
    expanded: str
    product_phrase: str
    category: Optional[CategoryProfile] = None
    budget: Optional[float] = None
    currency: str = "AED"
    wants_best: bool = False
    brand_terms: list[str] = field(default_factory=list)


def detect_category(query: str) -> Optional[CategoryProfile]:
    """Return the product type the query is asking for, if we know it."""
    if wants_electric_scooter(query):
        return CATEGORIES[0]
    tokens = set(query_match_terms(query))
    lowered = expand_shopper_query(query).lower()
    if tokens & {"earbuds", "earbud", "earphones", "earphone"}:
        return CATEGORIES[1]
    if tokens & {"headphones", "headphone"}:
        return CATEGORIES[2]
    if "chair" in tokens or "office chair" in lowered:
        return CATEGORIES[3]
    return None


def parse_intent(query: str, default_currency: str = "AED") -> QueryIntent:
    """Turn a typed query into an expanded shopping intent."""
    expanded = expand_shopper_query(query)
    category = detect_category(query)
    generic = [term for term in query_match_terms(query) if term not in required_terms(query)]
    if category:
        phrase = category.phrase
    elif generic:
        phrase = " ".join(generic)
    else:
        phrase = " ".join(query_match_terms(query)) or expanded
    wants_best = bool(re.search(r"\bbest\b", query, re.I))
    return QueryIntent(
        original=query.strip(),
        expanded=expanded,
        product_phrase=phrase,
        category=category,
        budget=extract_budget(query),
        currency=extract_budget_currency(query, default_currency),
        wants_best=wants_best,
        brand_terms=required_terms(query),
    )


def catalog_search_queries(query: str, country_term: str) -> list[str]:
    """Named-model searches, the shopping-index equivalent of a knowledge graph."""
    intent = parse_intent(query)
    if not intent.category or not intent.category.popular:
        return []
    if intent.brand_terms:
        return []
    place = country_term.strip()
    queries: list[str] = []
    for name in intent.category.popular[:5]:
        queries.append(f'"{name}" {place}'.strip())
    return queries


def spec_collides_with_budget(query: str, text: str) -> bool:
    """True when a listing uses the budget number as watts/kg/ohms/karats."""
    budget = extract_budget(query)
    if budget is None:
        return False
    lowered = text.lower()
    amount = int(budget) if float(budget).is_integer() else budget
    if re.search(rf"\b{amount}\s*(?:w|watt|watts|kw)\b", lowered):
        return True
    if re.search(rf"\b{amount}\s*(?:ohm|ohms|kg|kgs)\b", lowered):
        return True
    if amount >= 1000 and float(amount).is_integer() and amount % 1000 == 0:
        kilos = int(amount) // 1000
        if re.search(rf"\b{kilos}\s*k(?:w|ohm|g)\b", lowered):
            return True
        if re.search(rf"\b{kilos}k\s*(?:w|watt|ohm|gold|yellow)\b", lowered):
            return True
    return False


def price_band(query: str, base_currency: str) -> Optional[tuple[float, float]]:
    """Typical buyable price range for this product type, in ``base_currency``."""
    category = detect_category(query)
    if category is None:
        return None
    lo = convert_to_base(category.price_aed[0], "AED", base_currency)
    hi = convert_to_base(category.price_aed[1], "AED", base_currency)
    budget = budget_in_base(query, base_currency)
    if budget is not None:
        hi = min(hi, budget * 1.08)
        lo = min(lo, budget * 0.08)
    return (lo, hi)


def price_outside_band(query: str, amount_base: float, base_currency: str) -> bool:
    """True for crumbs (AED 25 “scooters”) and luxury outliers vs the category."""
    band = price_band(query, base_currency)
    if band is None or amount_base <= 0:
        return False
    lo, hi = band
    return amount_base < lo or amount_base > hi


def popular_model_bonus(query: str, title: str) -> float:
    """Small boost when a ‘best X’ query hits a well-known model name."""
    intent = parse_intent(query)
    if not intent.wants_best or not intent.category:
        return 0.0
    lowered = title.lower()
    for name in intent.category.popular:
        if name.lower() in lowered:
            return 0.12
        tokens = name.lower().split()
        if len(tokens) >= 3 and all(token in lowered for token in tokens[:3]):
            return 0.08
    return 0.0


def build_overview(query: str, country_name: str, currency: str, answers: list) -> str:
    """A short AI-overview-style summary of the ranked picks."""
    intent = parse_intent(query, currency)
    product = intent.product_phrase or "products"
    if intent.budget is not None:
        cap = int(intent.budget) if float(intent.budget).is_integer() else intent.budget
        head = f"Best {product}s under {cap} {intent.currency}" if not product.endswith("s") else (
            f"Best {product} under {cap} {intent.currency}"
        )
    else:
        head = f"Best {product}s" if not product.endswith("s") else f"Best {product}"
    head += f" in {country_name}."

    if intent.category and intent.category.key == "electric_scooter":
        head += (
            " These are rideable electric kick scooters from local stores and sellers "
            "that ship there — not 10K gold, resistors, washers, or spare parts."
        )

    named: list[str] = []
    for pick in answers:
        item = getattr(pick, "item", None)
        if item is None:
            continue
        title = re.split(r"\s+[|\-–]\s+", item.title, maxsplit=1)[0].strip()
        title = re.sub(r"\s+", " ", title)
        if len(title) > 64:
            title = title[:63].rstrip() + "…"
        if item.price is not None:
            named.append(f"{title} ({item.price.format(currency)})")
        else:
            named.append(title)
        if len(named) >= 3:
            break
    if named:
        head += " Top picks: " + "; ".join(named) + "."
    elif intent.expanded.lower() != intent.original.lower():
        head += f" Searched as {intent.expanded}."
    return head
