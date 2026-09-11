"""Country availability: local stores vs sellers that ship vs other-country listings."""

from __future__ import annotations

from config import AppConfig
from location import (
    classify_listing,
    country_from_headers,
    country_from_query,
    country_from_timezone,
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


def test_us_storefront_tld_is_foreign_for_uae() -> None:
    ae = get_country("AE")
    us_brand = classify_listing(
        "https://www.naveetech.us/products/navee-gt3",
        "naveetech.us",
        ae,
    )
    amazon_ae = classify_listing(
        "https://www.amazon.ae/NAVEE-Electric-Scooter/dp/B0TEST",
        "amazon.ae",
        ae,
    )
    assert us_brand.kind == "foreign"
    assert amazon_ae.kind == "local"


def test_rank_amazon_ae_over_us_brand_site() -> None:
    config = AppConfig()
    config.country_code = "AE"
    amazon = ProductItem(
        title="NAVEE GT3 Pro Electric Scooter for Adults, 60KM Max",
        url="https://www.amazon.ae/NAVEE-Electric-Scooter/dp/B0TEST",
        source_domain="amazon.ae",
        description="NAVEE GT3 Pro electric scooter",
        price=PriceInfo(amount=1619, currency="AED", original_text="AED 1619", amount_base=1619),
        rating=4.4,
        review_count=12,
    )
    us_site = ProductItem(
        title="NAVEE GT3 | Commuter Electric Scooter",
        url="https://www.naveetech.us/products/gt3",
        source_domain="naveetech.us",
        description="NAVEE GT3 electric scooter",
        price=PriceInfo(amount=419.99, currency="USD", original_text="$419.99", amount_base=1541),
        rating=4.7,
        review_count=118,
    )
    picks = rank_items([us_site, amazon], "navee gt3 electric scooter buy", config)
    urls = [pick.item.url for pick in picks.answers if pick.item]
    assert urls
    assert all("naveetech.us" not in url for url in urls)
    assert picks.best_overall is not None
    assert picks.best_overall.source_domain == "amazon.ae"


def test_us_brand_dotcom_is_foreign_for_uae() -> None:
    ae = get_country("AE")
    assert (
        classify_listing(
            "https://www.naveetech.com/products/gt3",
            "naveetech.com",
            ae,
        ).kind
        == "foreign"
    )
    assert (
        classify_listing(
            "https://eu.naveetech.com/products/gt3",
            "eu.naveetech.com",
            ae,
        ).kind
        == "foreign"
    )
    assert (
        classify_listing(
            "https://www.wellbots.com/products/navee-gt3",
            "wellbots.com",
            ae,
        ).kind
        == "foreign"
    )
    assert (
        classify_listing(
            "https://www.naveetech.ae/products/gt3",
            "naveetech.ae",
            ae,
        ).kind
        == "local"
    )


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
    assert country_from_timezone("Asia/Dubai") == "AE"
    assert country_from_timezone("Asia/Kolkata") == "IN"
    assert country_from_timezone("America/New_York") == "US"
    assert country_from_timezone("UTC") is None


def test_localize_and_marketplace_queries() -> None:
    ae = get_country("AE")
    assert localize_query("noise cancelling headphones", ae) == "noise cancelling headphones UAE"
    assert localize_query("earbuds under 200 AED", ae) == "earbuds under 200 AED"
    queries = marketplace_site_queries("wireless earbuds", ae)
    assert any(row == "wireless earbuds site:amazon.ae" for row in queries)
    assert any("site:noon.com" in row for row in queries)
    assert any("site:aliexpress.com" in row for row in queries)
    assert not any(" OR " in row for row in queries)


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
