"""Query understanding: intent, price bands, and overview copy."""

from __future__ import annotations

from config import AppConfig
from intent import (
    build_overview,
    catalog_search_queries,
    parse_intent,
    spec_collides_with_budget,
)
from location import resolve_country
from models import LabeledPick, PriceInfo, ProductItem


def test_parse_e_scooter_under_10k() -> None:
    intent = parse_intent("best e scooter under 10k aed")
    assert intent.expanded == "best electric scooter under 10000 aed"
    assert intent.product_phrase == "electric scooter"
    assert intent.category is not None
    assert intent.category.key == "electric_scooter"
    assert intent.budget == 10000
    assert intent.currency == "AED"
    assert intent.wants_best is True


def test_catalog_queries_search_named_scooters() -> None:
    queries = catalog_search_queries("best e scooter under 10k aed", "UAE")
    blob = " ".join(queries).lower()
    assert "xiaomi electric scooter 6 pro" in blob
    assert "crony" in blob


def test_brand_query_searches_local_market() -> None:
    queries = catalog_search_queries("navee gt3 electric scooter buy", "UAE")
    blob = " ".join(queries).lower()
    assert "navee gt3" in blob
    assert "uae" in blob


def test_vsett_scooter_buy_is_an_electric_scooter_search() -> None:
    from querying import wants_electric_scooter

    assert wants_electric_scooter("vsett scooter buy")
    intent = parse_intent("vsett scooter buy")
    assert intent.category is not None
    assert intent.category.key == "electric_scooter"


def test_spec_collision_watts_and_ohms() -> None:
    query = "best e scooter under 10k aed"
    assert spec_collides_with_budget(query, "10000W Dual Motor Electric Scooter")
    assert spec_collides_with_budget(query, "100pcs 10k Ohm Resistor")
    assert not spec_collides_with_budget(query, "Xiaomi Electric Scooter 6 Pro")


def test_overview_names_top_picks() -> None:
    item = ProductItem(
        title="Xiaomi Electric Scooter 6 Max",
        url="https://www.mi.com/ae-en/product/xiaomi-electric-scooter-6-max/",
        source_domain="mi.com",
        price=PriceInfo(amount=2556, currency="AED", original_text="AED 2556", amount_base=2556),
    )
    text = build_overview(
        "best e scooter under 10k aed",
        "United Arab Emirates",
        "AED",
        [LabeledPick("best_overall", "Best match", "mix", item)],
    )
    assert "electric scooter" in text.lower()
    assert "10000" in text or "10,000" in text
    assert "Xiaomi" in text
    assert "kick scooter" in text.lower() or "not 10K gold" in text


def test_aed_query_shops_uae_from_us_timezone() -> None:
    profile = resolve_country(
        AppConfig(),
        query="best e scooter under 10k aed",
        timezone="America/New_York",
    )
    assert profile.code == "AE"
    assert profile.currency == "AED"
