"""Exact query matching: brand/model required, spare parts downranked."""

from __future__ import annotations

from models import PriceInfo, ProductItem
from querying import (
    accessory_multiplier,
    hit_is_plausible,
    precise_search_query,
    required_terms,
    tokenize,
)
from scoring import rank_items, relevance_score
from config import AppConfig


def _item(title: str, url: str, domain: str, amount: float | None, description: str = "") -> ProductItem:
    price = None
    if amount is not None:
        price = PriceInfo(amount=amount, currency="AED", original_text=str(amount), amount_base=amount)
    return ProductItem(
        title=title,
        url=url,
        source_domain=domain,
        description=description,
        price=price,
        rating=4.5,
    )


def test_tokenize_keeps_plus_model() -> None:
    assert tokenize("vsett 10+ scooter") == ["vsett", "10+", "scooter"]
    assert "10+" in tokenize("VSETT 10 Plus Electric Scooter")
    assert "10+" not in tokenize("Wide tube 10x3.0 Dubai Scooter Service")


def test_required_terms_are_brand_and_model() -> None:
    assert required_terms("vsett 10+ scooter") == ["vsett", "10+"]
    assert required_terms("wireless earbuds under 200 AED") == []


def test_precise_query_quotes_model_and_excludes_parts() -> None:
    rewritten = precise_search_query("vsett 10+ scooter")
    assert '"vsett 10+"' in rewritten
    assert "scooter" in rewritten
    assert "-mudguard" in rewritten
    assert "-compatible" in rewritten
    assert "-tube" not in rewritten


def test_mudguard_is_not_plausible_for_scooter_query() -> None:
    query = "vsett 10+ scooter"
    assert hit_is_plausible(query, "VSETT 10+ Electric Scooter 60V")
    assert hit_is_plausible(query, "VSETT 10 Electric Scooter Max Speed 80 kmh")
    assert hit_is_plausible(
        query,
        "VSETT Electric Scooter",
        url="http://www.vsett.com/product/5.html",
    )
    assert not hit_is_plausible(
        query, "LHAIQQ Universal Mudguard Compatible with VSETT 10+ MUKUTA 10"
    )
    assert not hit_is_plausible(
        query,
        "Disc brake rotor 145mm",
        url="https://www.whizz.ae/product/electric-scooter-disc-brake-rotor-for-vsett-10-replacement-parts",
    )
    assert accessory_multiplier(query, "ZAPYVET For VSETT, 10+ Spare Steering Damper") < 0.5
    assert accessory_multiplier(
        query,
        "Guidão de borracha antiderrapante, extensões de peça para vsett 10 plus",
    ) < 0.5


def test_relevance_prefers_the_scooter_over_parts() -> None:
    query = "vsett 10+ scooter"
    scooter = _item(
        "VSETT 10 Plus Electric Scooter 60V",
        "https://www.noon.com/vsett-10-plus",
        "noon.com",
        4200,
        "VSETT 10+ electric scooter",
    )
    mudguard = _item(
        "LHAIQQ Universal Mudguard Compatible with VSETT 10+ MUKUTA 10 Zero",
        "https://www.amazon.ae/mudguard",
        "amazon.ae",
        35,
        "mudguard compatible with vsett 10+ scooter",
    )
    tube = _item(
        "Wide tube 10x3.0 / 255x80 | Dubai Scooter Service",
        "https://scooterservice.ae/tube",
        "scooterservice.ae",
        25,
        "inner tube for electric scooter",
    )
    kit = _item(
        "NOGRAX Electric Scooter Steering Damper Kit For VSETT 10+",
        "https://www.amazon.ae/damper",
        "amazon.ae",
        80,
        "spare kit for vsett 10+ scooter",
    )
    assert relevance_score(query, scooter) > 0.5
    assert relevance_score(query, mudguard) < 0.2
    assert relevance_score(query, tube) < 0.2
    assert relevance_score(query, kit) < 0.2

    picks = rank_items([mudguard, tube, kit, scooter], query, AppConfig())
    titles = [pick.item.title for pick in picks.answers if pick.item]
    assert titles
    assert all("Mudguard" not in title for title in titles)
    assert all("tube" not in title.lower() for title in titles)
    assert all("Damper" not in title for title in titles)
    assert picks.best_overall is not None
    assert "Electric Scooter" in picks.best_overall.title
    assert picks.best_price is not None
    assert picks.best_price.url == scooter.url
