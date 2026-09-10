"""Country availability: local stores vs sellers that ship vs other-country listings."""

from __future__ import annotations

from config import AppConfig
from location import (
    classify_listing,
    country_from_headers,
    country_from_query,
    get_country,
    localize_query,
    marketplace_site_queries,
)
from models import PriceInfo, ProductItem
from scoring import rank_items


def test_local_uae_storefronts() -> None:
    ae = get_country("AE")
    noon = classify_listing("https://www.noon.com/uae-en/earbuds", "noon.com", ae)
    amazon_ae = classify_listing("https://www.amazon.ae/dp/B0TEST", "amazon.ae", ae)
    assert noon.kind == "local"
    assert amazon_ae.kind == "local"
    assert "United Arab Emirates" in noon.label


def test_aliexpress_ships_to_uae() -> None:
    ae = get_country("AE")
    listing = classify_listing(
        "https://www.aliexpress.com/item/100500.html", "aliexpress.com", ae
    )
    assert listing.kind == "ships"
    assert "Ships to" in listing.label


def test_country_subdomain_is_not_treated_as_local() -> None:
    ae = get_country("AE")
    saudi = classify_listing(
        "https://saudi.sharafdg.com/product/earbuds",
        "saudi.sharafdg.com",
        ae,
    )
    uae = classify_listing(
        "https://uae.sharafdg.com/product/earbuds",
        "uae.sharafdg.com",
        ae,
    )
    assert saudi.kind == "foreign"
    assert uae.kind == "local"


def test_us_amazon_is_foreign_for_uae() -> None:
    ae = get_country("AE")
    listing = classify_listing("https://www.amazon.com/dp/B0TEST", "amazon.com", ae)
    assert listing.kind == "foreign"


def test_flipkart_is_local_in_india_foreign_in_uae() -> None:
    india = get_country("IN")
    ae = get_country("AE")
    url = "https://www.flipkart.com/wireless-earbuds/p/itm123"
    assert classify_listing(url, "flipkart.com", india).kind == "local"
    assert classify_listing(url, "flipkart.com", ae).kind == "foreign"


def test_query_hints_and_headers() -> None:
    assert country_from_query("wireless earbuds under 200 AED") == "AE"
    assert country_from_query("earbuds under 2000 INR") == "IN"
    assert country_from_headers({"CF-IPCountry": "IN"}) == "IN"
    assert country_from_headers({"Accept-Language": "en-GB,en;q=0.9"}) == "GB"


def test_localize_and_marketplace_queries() -> None:
    ae = get_country("AE")
    assert localize_query("noise cancelling headphones", ae) == "noise cancelling headphones UAE"
    assert localize_query("earbuds under 200 AED", ae) == "earbuds under 200 AED"
    queries = marketplace_site_queries("wireless earbuds", ae)
    assert any("site:amazon.ae" in row for row in queries)
    assert any("site:noon.com" in row for row in queries)
    assert any("site:aliexpress.com" in row for row in queries)


def test_ranking_prefers_local_over_cheaper_foreign() -> None:
    config = AppConfig()
    config.country_code = "AE"
    items = [
        ProductItem(
            title="Wireless Earbuds USA deal",
            url="https://www.amazon.com/dp/CHEAP",
            source_domain="amazon.com",
            description="wireless earbuds",
            price=PriceInfo(amount=19, currency="USD", original_text="$19", amount_base=70),
            rating=4.8,
        ),
        ProductItem(
            title="Wireless Earbuds UAE",
            url="https://www.noon.com/uae-en/earbuds",
            source_domain="noon.com",
            description="wireless earbuds",
            price=PriceInfo(amount=149, currency="AED", original_text="AED 149", amount_base=149),
            rating=4.4,
        ),
        ProductItem(
            title="Wireless Earbuds AliExpress",
            url="https://www.aliexpress.com/item/1",
            source_domain="aliexpress.com",
            description="wireless earbuds",
            price=PriceInfo(amount=12, currency="USD", original_text="$12", amount_base=44),
            rating=4.1,
        ),
        ProductItem(
            title="Wireless Earbuds Amazon AE",
            url="https://www.amazon.ae/dp/LOCAL",
            source_domain="amazon.ae",
            description="wireless earbuds",
            price=PriceInfo(amount=129, currency="AED", original_text="AED 129", amount_base=129),
            rating=4.3,
        ),
    ]
    picks = rank_items(items, "wireless earbuds", config)
    urls = [pick.item.url for pick in picks.answers if pick.item]
    assert all("amazon.com" not in url for url in urls)
    assert any("noon.com" in url or "amazon.ae" in url for url in urls)
    assert any("aliexpress.com" in url for url in urls)
    assert picks.best_price is not None
    assert "amazon.com" not in picks.best_price.url
    assert picks.country_code == "AE"
