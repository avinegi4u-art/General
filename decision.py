"""Name one listing to buy, then show the price and rating given up elsewhere.

A chat agent can pick a product and hide the alternatives. This module keeps
the five-role shortlist and adds an auditable buy: the price gap, the star
gap, delivery to the shopper's country, and whether the page actually printed
a price and a rating.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from models import LabeledPick, ProductItem, RankedPicks
from querying import budget_in_base
from search import looks_like_index_page

_PRICE_INTENT = re.compile(r"\b(cheapest|lowest price|best price|cheap)\b", re.I)
_RATED_INTENT = re.compile(r"\b(best rated|highest rated|top rated)\b", re.I)
_VALUE_INTENT = re.compile(r"\b(best value|value for money)\b", re.I)
_TITLE_SPLIT = re.compile(r"\s+[|\-–]\s+")
_TOKEN = re.compile(r"[a-z0-9+]+")
_TITLE_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "buy",
        "best",
        "new",
        "official",
        "online",
        "shop",
        "store",
        "price",
        "sale",
        "free",
        "shipping",
        "delivery",
        "your",
        "you",
    }
)


def build_decision(picks: RankedPicks) -> dict[str, Any]:
    """Return the buy, the evidence checks, and a tradeoff for every shortlisted row."""
    answers = [
        pick
        for pick in picks.answers
        if pick.item is not None and not looks_like_index_page(pick.item.url, pick.item.title)
    ]
    if not answers:
        return {"verdict": None, "checks": [], "rows": [], "spread": "", "same_title": "", "hold": ""}
    buy = _select_buy(picks, answers)
    if buy is None or buy.item is None:
        return {"verdict": None, "checks": [], "rows": [], "spread": "", "same_title": "", "hold": ""}

    currency = picks.base_currency
    item = buy.item
    budget = budget_in_base(picks.query, currency)
    checks = _checks(item, picks.country_name, budget, currency)
    holds = [check["label"] for check in checks if check["status"] == "fail"]
    cheapest = _cheapest(answers)
    top_rated = _top_rated(answers)
    spread = _spread(item, cheapest, top_rated, currency)
    same_title = _same_title_note(item, answers, currency)
    rows = [
        _row(pick, buy, currency)
        for pick in answers
    ]
    return {
        "verdict": {
            "pick_id": buy.key,
            "label": buy.label,
            "title": _display_title(item.title),
            "headline": f"Buy {_display_title(item.title)} from {item.source_domain}",
            "reason": _reason(picks.query, buy, item, cheapest, picks.country_name, currency),
            "url": item.url,
            "source": item.source_domain,
            "price_display": item.price.format(currency) if item.price else "",
            "rating_display": _rating_display(item),
            "availability": item.availability_label or "Availability unclear",
        },
        "checks": checks,
        "hold": holds[0] if holds else "",
        "spread": spread,
        "same_title": same_title,
        "rows": rows,
    }


def _select_buy(picks: RankedPicks, answers: list[LabeledPick]) -> Optional[LabeledPick]:
    """Pick the category the query asked for, even when that URL also won another slot.

    Answer rows are unique by URL, so the cheapest listing can be labeled Best
    match and never appear under the Best price key. The buy still follows the
    price, rating, or value winner.
    """
    if _PRICE_INTENT.search(picks.query):
        key, label, item = "best_price", "Best price", picks.best_price
    elif _RATED_INTENT.search(picks.query):
        key, label, item = "best_rated", "Best rated", picks.best_rated
    elif _VALUE_INTENT.search(picks.query):
        key, label, item = "best_value", "Best value", picks.best_value
    else:
        key, label, item = "best_overall", "Best match", picks.best_overall
    if item is None:
        return answers[0] if answers else None
    for pick in answers:
        if pick.item is not None and pick.item.url == item.url and pick.key == key:
            return pick
    return LabeledPick(key, label, "", item)


def _checks(
    item: ProductItem,
    country_name: str,
    budget: Optional[float],
    currency: str,
) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if item.price_base and item.price_base > 0 and item.price is not None:
        checks.append(
            {
                "id": "price",
                "status": "pass",
                "label": f"Price is on the page ({item.price.format(currency)})",
            }
        )
    else:
        checks.append({"id": "price", "status": "fail", "label": "Price is not on the page"})

    if item.rating_is_default or item.rating is None:
        checks.append({"id": "rating", "status": "warn", "label": "No star rating on the page"})
    else:
        checks.append(
            {
                "id": "rating",
                "status": "pass",
                "label": f"Star rating is on the page ({item.rating:.1f}/5)",
            }
        )

    if item.review_count is None:
        checks.append({"id": "reviews", "status": "warn", "label": "Review count is not on the page"})
    elif item.review_count >= 20:
        checks.append({"id": "reviews", "status": "pass", "label": f"{item.review_count} reviews"})
    elif item.review_count > 0:
        checks.append(
            {"id": "reviews", "status": "warn", "label": f"Only {item.review_count} reviews"}
        )
    else:
        checks.append({"id": "reviews", "status": "fail", "label": "No reviews"})

    if item.availability == "local":
        checks.append(
            {"id": "delivery", "status": "pass", "label": f"Sold in {country_name}"}
        )
    elif item.availability == "ships":
        checks.append(
            {"id": "delivery", "status": "warn", "label": f"Ships to {country_name}"}
        )
    elif item.availability == "foreign":
        checks.append(
            {
                "id": "delivery",
                "status": "fail",
                "label": f"May not ship to {country_name}",
            }
        )
    else:
        checks.append({"id": "delivery", "status": "warn", "label": "Delivery is unclear"})

    if budget is not None and item.price_base and item.price_base > 0:
        if item.price_base <= budget:
            checks.append(
                {
                    "id": "budget",
                    "status": "pass",
                    "label": f"Inside your {money(budget, currency)} budget",
                }
            )
        else:
            over = item.price_base - budget
            checks.append(
                {
                    "id": "budget",
                    "status": "fail",
                    "label": (
                        f"{money(over, currency)} over your {money(budget, currency)} budget"
                    ),
                }
            )
    return checks


def _reason(
    query: str,
    buy: LabeledPick,
    item: ProductItem,
    cheapest: Optional[LabeledPick],
    country_name: str,
    currency: str,
) -> str:
    if buy.key == "best_price" and _PRICE_INTENT.search(query):
        opening = "You asked for the lowest price, so this is the cheapest relevant listing"
    elif buy.key == "best_rated" and _RATED_INTENT.search(query):
        opening = "You asked for the highest rating, so this is the top-rated relevant listing"
    elif buy.key == "best_value" and _VALUE_INTENT.search(query):
        opening = "You asked for value, so this is the strongest quality for the price"
    else:
        opening = "This is the strongest mix of match, price, rating, and delivery"

    facts: list[str] = []
    buy_is_cheapest = (
        cheapest is not None
        and cheapest.item is not None
        and item.price_base is not None
        and cheapest.item.price_base is not None
        and cheapest.item.url == item.url
    )
    if item.price is not None and item.price_base:
        if buy_is_cheapest and buy.key != "best_price":
            facts.append(f"it is the lowest price in this shortlist at {item.price.format(currency)}")
        elif (
            cheapest is not None
            and cheapest.item is not None
            and cheapest.item.price_base
            and item.price_base > cheapest.item.price_base + 0.5
        ):
            delta = item.price_base - cheapest.item.price_base
            facts.append(
                f"it costs {money(delta, currency)} more than the cheapest shortlisted price"
            )
    else:
        facts.append("the page did not show a price")

    if not item.rating_is_default and item.rating:
        if item.review_count:
            facts.append(f"the page shows {item.rating:.1f}/5 from {item.review_count} reviews")
        else:
            facts.append(f"the page shows {item.rating:.1f}/5")
    else:
        facts.append("the page did not show a star rating")

    if item.availability == "local":
        facts.append(f"it is sold in {country_name}")
    elif item.availability == "ships":
        facts.append(f"it ships to {country_name}")
    elif item.availability == "foreign":
        facts.append(f"it may not ship to {country_name}")
    else:
        facts.append("delivery is unclear")

    if not facts:
        return opening + "."
    if len(facts) == 1:
        return f"{opening} because {facts[0]}."
    return f"{opening} because {', '.join(facts[:-1])}, and {facts[-1]}."


def _spread(
    buy: ProductItem,
    cheapest: Optional[LabeledPick],
    top_rated: Optional[LabeledPick],
    currency: str,
) -> str:
    parts: list[str] = []
    if (
        buy.price_base
        and cheapest is not None
        and cheapest.item is not None
        and cheapest.item.price_base
    ):
        delta = buy.price_base - cheapest.item.price_base
        if cheapest.item.url == buy.url:
            parts.append("Lowest price in this shortlist")
        elif delta > 0.5 and cheapest.item.price is not None:
            parts.append(
                f"{money(delta, currency)} more than {cheapest.label.lower()} "
                f"({cheapest.item.price.format(currency)})"
            )
    if top_rated is not None and top_rated.item is not None and top_rated.item.rating:
        if top_rated.item.url == buy.url:
            parts.append("Highest star rating in this shortlist")
        elif not buy.rating_is_default and buy.rating is not None:
            gap = top_rated.item.rating - buy.rating
            if gap >= 0.15:
                parts.append(
                    f"{gap:.1f} stars under the {top_rated.label} row ({top_rated.item.rating:.1f}/5)"
                )
    if not parts:
        return ""
    return ". ".join(parts) + "."


def _same_title_note(buy: ProductItem, answers: list[LabeledPick], currency: str) -> str:
    if not buy.price_base:
        return ""
    twins: list[ProductItem] = []
    for pick in answers:
        other = pick.item
        if other is None or other.url == buy.url or not other.price_base:
            continue
        if not _near_title(buy.title, other.title):
            continue
        ratio = other.price_base / buy.price_base
        if ratio < 0.25 or ratio > 4:
            continue
        twins.append(other)
    if not twins:
        return ""
    cheaper = [item for item in twins if item.price_base and item.price_base < buy.price_base - 0.5]
    if cheaper:
        best = min(cheaper, key=lambda item: item.price_base or 0)
        delta = (buy.price_base or 0) - (best.price_base or 0)
        return f"{best.source_domain} lists a near-identical title for {money(delta, currency)} less."
    pricier = max(twins, key=lambda item: item.price_base or 0)
    delta = (pricier.price_base or 0) - (buy.price_base or 0)
    if delta <= 0.5:
        return ""
    return f"A near-identical title on {pricier.source_domain} costs {money(delta, currency)} more."


def _row(pick: LabeledPick, buy: LabeledPick, currency: str) -> dict[str, Any]:
    item = pick.item
    assert item is not None and buy.item is not None
    is_buy = item.url == buy.item.url
    return {
        "id": pick.key,
        "label": pick.label,
        "title": _display_title(item.title),
        "url": item.url,
        "source": item.source_domain,
        "price_display": item.price.format(currency) if item.price else "Price not on the page",
        "rating_display": _rating_display(item),
        "availability": item.availability_label or "Availability unclear",
        "edge": "The listing to buy." if is_buy else _edge(item, buy.item, currency),
        "is_buy": is_buy,
    }


def _edge(item: ProductItem, buy: ProductItem, currency: str) -> str:
    bits: list[str] = []
    if item.price_base and buy.price_base:
        delta = buy.price_base - item.price_base
        if delta > 0.5:
            bits.append(f"Save {money(delta, currency)} versus the buy")
        elif delta < -0.5:
            bits.append(f"{money(-delta, currency)} more than the buy")
        else:
            bits.append("About the same price as the buy")
    elif not item.price_base:
        bits.append("Price was not on the page")
    if (
        item.rating is not None
        and buy.rating is not None
        and not item.rating_is_default
        and not buy.rating_is_default
    ):
        gap = item.rating - buy.rating
        if gap >= 0.15:
            bits.append(f"{gap:.1f} stars higher")
        elif gap <= -0.15:
            bits.append(f"{abs(gap):.1f} stars lower")
    if item.availability != buy.availability and item.availability_label:
        bits.append(item.availability_label)
    if not bits:
        return "Another listing in the shortlist."
    if len(bits) == 1:
        return bits[0] + "."
    return ". ".join(bits[:-1]) + f". {bits[-1]}."


def _cheapest(answers: list[LabeledPick]) -> Optional[LabeledPick]:
    priced = [
        pick
        for pick in answers
        if pick.item is not None and pick.item.price_base and pick.item.price_base > 0
    ]
    if not priced:
        return None
    return min(priced, key=lambda pick: pick.item.price_base or 0)  # type: ignore[union-attr]


def _top_rated(answers: list[LabeledPick]) -> Optional[LabeledPick]:
    rated = [
        pick
        for pick in answers
        if pick.item is not None and pick.item.rating and not pick.item.rating_is_default
    ]
    if not rated:
        return None
    return max(
        rated,
        key=lambda pick: (pick.item.rating or 0, pick.item.review_count or 0),  # type: ignore[union-attr]
    )


def _rating_display(item: ProductItem) -> str:
    if item.rating_is_default or item.rating is None:
        return "No stars on the page"
    if item.review_count:
        return f"{item.rating:.1f}/5 from {item.review_count} reviews"
    return f"{item.rating:.1f}/5"


def _display_title(title: str) -> str:
    """First product name, splitting store separators and titles glued together."""
    short = _TITLE_SPLIT.split(title, maxsplit=1)[0].strip()
    short = re.sub(r"\s+", " ", short)
    pieces = re.split(r"(?<=[a-z])(?=[A-Z])", short)
    if len(pieces) > 1 and len(pieces[0].strip()) >= 24:
        short = pieces[0].strip()
    if len(short) > 90:
        return short[:89].rstrip() + "…"
    return short


def _near_title(left: str, right: str) -> bool:
    a = _title_tokens(left)
    b = _title_tokens(right)
    if len(a) < 2 or len(b) < 2:
        return False
    shared = a & b
    if len(shared) < 2:
        return False
    return len(shared) / len(a | b) >= 0.55


def _title_tokens(title: str) -> set[str]:
    return {token for token in _TOKEN.findall(title.lower()) if token not in _TITLE_STOP and len(token) > 1}


def money(amount: float, currency: str) -> str:
    """Format a comparison delta without trailing zeros on whole amounts."""
    rounded = round(float(amount), 2)
    if abs(rounded - round(rounded)) < 0.001:
        return f"{int(round(rounded))} {currency}"
    return f"{rounded:.2f} {currency}"
