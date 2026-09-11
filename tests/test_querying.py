"""Exact query matching: brand/model required, spare parts downranked."""

from __future__ import annotations

from models import PriceInfo, ProductItem
from querying import (
    accessory_multiplier,
    expand_shopper_query,
    hit_is_plausible,
    prefer_query_aware_title,
    precise_search_query,
    product_core_query,
    query_match_terms,
    required_terms,
    shopping_followup_queries,
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


def test_e_scooter_under_10k_is_not_a_10k_token_search() -> None:
    query = "best e scooter under 10k aed"
    assert expand_shopper_query(query) == "best electric scooter under 10000 aed"
    assert "10k" not in query_match_terms(query)
    assert required_terms(query) == []
    assert query_match_terms(query) == ["electric", "scooter"]

    rewritten = precise_search_query(query)
    assert '"electric scooter"' in rewritten
    assert "under 10000 AED" in rewritten
    assert "10k" not in rewritten.lower()
    assert "-resistor" in rewritten
    assert "-washer" in rewritten
    assert "-earrings" in rewritten
    assert "-thermometer" in rewritten
    assert "-mobility" in rewritten

    follows = shopping_followup_queries(query, "UAE")
    assert any("xiaomi" in item.lower() for item in follows)

    assert hit_is_plausible(query, "Xiaomi Electric Scooter 6 Pro")
    assert hit_is_plausible(query, "CRONY M365 MAX Electric Scooter")
    assert not hit_is_plausible(
        query,
        "Thermometer for motorcycle scooter M8 10K for UU125 UY125",
    )
    assert not hit_is_plausible(query, "Geepas 10KG Semi Automatic Twin Hub Washer")
    assert not hit_is_plausible(query, "100pcs 10k Ohm Resistor 1 4w 25 Watt")
    assert not hit_is_plausible(
        query, "Buy Jewelili Button Stud Earrings 10K Yellow Gold, Capri Blue"
    )


def test_rank_e_scooter_prefers_xiaomi_over_10k_lookalikes() -> None:
    query = "best e scooter under 10k aed"
    xiaomi = _item(
        "Xiaomi Electric Scooter 6 Pro",
        "https://www.noon.com/xiaomi-electric-scooter-6-pro",
        "noon.com",
        2111.69,
        "Xiaomi electric scooter",
    )
    crony = _item(
        "CRONY M365 MAX Electric Scooter",
        "https://www.noon.com/crony-m365-max",
        "noon.com",
        999.0,
        "electric scooter",
    )
    thermometer = _item(
        "Thermometer for motorcycle scooter M8 10K for UU125 UY125",
        "https://www.alfashop.ae/thermometer",
        "alfashop.ae",
        49.0,
        "motorcycle scooter thermometer",
    )
    washer = _item(
        "Geepas 10KG Semi Automatic Twin Hub Washer GSWM6467-10K",
        "https://www.alfashop.ae/washer",
        "alfashop.ae",
        499.0,
        "twin hub washer",
    )
    resistor = _item(
        "100pcs 10k Ohm Resistor 1 4w 25 Watt",
        "https://desertcart.ae/resistor",
        "desertcart.ae",
        None,
        "metal film resistor",
    )
    earrings = _item(
        "Jewelili Button Stud Earrings 10K Yellow Gold",
        "https://www.carrefouruae.com/earrings",
        "carrefouruae.com",
        None,
        "10K gold earrings",
    )

    assert relevance_score(query, xiaomi) > 0.5
    assert relevance_score(query, crony) > 0.5
    assert relevance_score(query, thermometer) < 0.2
    assert relevance_score(query, washer) < 0.2
    assert relevance_score(query, resistor) < 0.2
    assert relevance_score(query, earrings) < 0.2

    picks = rank_items(
        [thermometer, washer, resistor, earrings, crony, xiaomi],
        query,
        AppConfig(),
    )
    titles = [pick.item.title for pick in picks.answers if pick.item]
    assert titles
    joined = " ".join(titles).lower()
    assert "xiaomi" in joined or "crony" in joined
    assert "washer" not in joined
    assert "resistor" not in joined
    assert "earring" not in joined
    assert "thermometer" not in joined
    assert picks.best_overall is not None
    assert "Electric Scooter" in picks.best_overall.title
    assert picks.best_price is not None
    assert picks.best_price.url == crony.url
    assert any("Interpreted as" in note for note in picks.notes)


def test_category_index_does_not_beat_named_scooter() -> None:
    query = "best e scooter under 10k aed"
    xiaomi = _item(
        "Xiaomi Electric Scooter 6 Max",
        "https://www.mi.com/ae-en/product/xiaomi-electric-scooter-6-max/",
        "mi.com",
        2556.0,
        "Xiaomi electric scooter",
    )
    jumbo = _item(
        "Electric Scooters at Best Prices in Dubai, UAE - Jumbo Electronics",
        "https://www.jumbo.ae/toys/scooters.html",
        "jumbo.ae",
        1499.0,
        "electric scooters",
    )
    assert relevance_score(query, xiaomi) > relevance_score(query, jumbo)
    picks = rank_items([jumbo, xiaomi], query, AppConfig())
    assert picks.best_overall is not None
    assert "Xiaomi" in picks.best_overall.title
    assert picks.best_price is not None
    assert picks.best_price.url == xiaomi.url


def test_10000w_listing_is_not_a_10000_aed_budget_match() -> None:
    query = "best e scooter under 10k aed"
    watts = _item(
        "EU Powerful 10000W Dual Motor 72V Electric Scooter",
        "https://www.aliexpress.com/item/1005009770906478.html",
        "aliexpress.com",
        2800,
        "10000W dual motor electric scooter",
    )
    xiaomi = _item(
        "Xiaomi Electric Scooter 6 Pro",
        "https://www.noon.com/xiaomi-electric-scooter-6-pro",
        "noon.com",
        2111,
        "Xiaomi electric scooter",
    )
    assert relevance_score(query, watts) < 0.2
    assert relevance_score(query, xiaomi) > relevance_score(query, watts)


def test_crumb_price_is_not_a_buyable_escooter() -> None:
    query = "best e scooter under 10k aed"
    crumb = _item(
        "Electric Scooters – Best Buy",
        "https://www.bestbuy.com/site/electric-scooters/pcmcat123",
        "bestbuy.com",
        25,
        "shop electric scooters for kids and adults",
    )
    assert relevance_score(query, crumb) <= 0.22


def test_product_core_query_skips_accessory_negatives() -> None:
    core = product_core_query("navee gt3 electric scooter buy")
    assert '"navee gt3"' in core
    assert "electric" in core
    assert "-mudguard" not in core
    assert "-kit" not in core


def test_amazon_ae_keeps_search_title_when_page_drops_gt3() -> None:
    query = "navee gt3 electric scooter buy"
    assert hit_is_plausible(
        query,
        "NAVEE Electric Scooter for Adults, 60KM Max",
        snippet="NAVEE GT3 Pro electric scooter",
        url="https://www.amazon.ae/NAVEE-Electric-Suspension-Commuting-Tubeless/dp/B0F1SYDQPP",
    )
    kept = prefer_query_aware_title(
        query,
        "NAVEE Electric Scooter for Adults, 60KM Max Range 1000W",
        "NAVEE GT3 Pro Electric Scooter for Adults, 60KM Max",
    )
    assert "GT3" in kept

    amazon = _item(
        kept,
        "https://www.amazon.ae/NAVEE-Electric-Suspension-Commuting-Tubeless/dp/B0F1SYDQPP",
        "amazon.ae",
        1619.10,
        "NAVEE GT3 Pro Electric Scooter for Adults",
    )
    us_site = _item(
        "NAVEE GT3 | Commuter Electric Scooter",
        "https://www.naveetech.us/products/gt3",
        "naveetech.us",
        1541,
        "NAVEE GT3 electric scooter",
    )
    wellbots = _item(
        "Navee GT3 E-Scooter",
        "https://www.wellbots.com/products/navee-gt3",
        "wellbots.com",
        1541,
        "Navee GT3 electric scooter",
    )
    amazon_no_model = _item(
        "NAVEE Electric Scooter for Adults, 60KM Max",
        "https://www.amazon.ae/NAVEE-Electric-Suspension/dp/B0F1SYDQPP",
        "amazon.ae",
        1619.10,
        "Rideable electric kick scooter",
    )
    config = AppConfig()
    config.country_code = "AE"
    picks = rank_items([us_site, wellbots, amazon], query, config)
    assert picks.best_overall is not None
    assert picks.best_overall.source_domain == "amazon.ae"
    urls = [pick.item.url for pick in picks.answers if pick.item]
    assert all("naveetech.us" not in url for url in urls)
    assert all("wellbots.com" not in url for url in urls)

    # Even if the model code never appears, the UAE Amazon brand page stays
    # eligible so a US storefront cannot win Best match.
    assert relevance_score(query, amazon_no_model) >= 0.35
    fallback = rank_items([us_site, wellbots, amazon_no_model], query, config)
    assert fallback.best_overall is not None
    assert fallback.best_overall.source_domain == "amazon.ae"


def test_polluted_snippet_does_not_make_unrelated_amazon_plausible() -> None:
    query = "navee gt3 electric scooter buy"
    polluted = "Buy NAVEE GT3 electric scooter online in the UAE"
    assert not hit_is_plausible(
        query,
        "Ninebot Kickscooter D38E Powered By Segway",
        snippet=polluted,
        url="https://www.amazon.ae/Ninebot-Kickscooter-Electric-Capacity/dp/B09SB7KY2Z",
    )
    assert not hit_is_plausible(
        query,
        "Navee scooter GT3 GT3 pro GT3 Max fast controller 32km",
        url="https://www.aliexpress.com/item/1005009469275859.html",
    )
    amazon = _item(
        "NAVEE GT3 Pro Electric Scooter for Adults, 60KM Max",
        "https://www.amazon.ae/NAVEE-Electric-Suspension-Commuting-Tubeless/dp/B0F1SYDQPP",
        "amazon.ae",
        1619.10,
        "NAVEE GT3 Pro",
    )
    realmax = _item(
        "REALMAX 8000w/72v Two Wheel Folding Off Road Electric Scooter",
        "https://www.amazon.ae/REALMAX-8000w-Folding-Electric-Scooter/dp/B099BHKLP6",
        "amazon.ae",
        4999,
        polluted,
    )
    controller = _item(
        "Navee scooter GT3 GT3 pro GT3 Max fast controller 32km",
        "https://www.aliexpress.com/item/1005009469275859.html",
        "aliexpress.com",
        80,
        "fast controller for navee gt3",
    )
    config = AppConfig()
    config.country_code = "AE"
    picks = rank_items([realmax, controller, amazon], query, config)
    assert picks.best_overall is not None
    assert picks.best_overall.source_domain == "amazon.ae"
    assert "REALMAX" not in picks.best_overall.title
    assert "controller" not in picks.best_overall.title.lower()
