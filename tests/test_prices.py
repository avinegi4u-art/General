"""Unit tests for price parsing, FX conversion, and HTML extraction."""

from __future__ import annotations

from config import convert_to_base
from scraper import extract_from_html, parse_amount, parse_price, parse_rating
from config import AppConfig


def test_parse_amount_thousands_and_decimal() -> None:
    assert parse_amount("1,299.50") == 1299.50
    assert parse_amount("199") == 199.0
    assert parse_amount("1.299,50") == 1299.50
    assert parse_amount("0") is None


def test_parse_price_aed_and_usd() -> None:
    aed = parse_price("Sony WF-C700N — AED 179 at noon.com", default_currency="AED")
    assert aed is not None
    assert aed.amount == 179
    assert aed.currency == "AED"
    assert aed.amount_base == 179

    usd = parse_price("Now $49.99", default_currency="AED", base_currency="AED")
    assert usd is not None
    assert usd.amount == 49.99
    assert usd.currency == "USD"
    assert usd.amount_base is not None
    assert usd.amount_base == convert_to_base(49.99, "USD", "AED")


def test_parse_price_symbol_after_amount() -> None:
    price = parse_price("Sale 89.00 €", default_currency="AED", base_currency="AED")
    assert price is not None
    assert price.currency == "EUR"
    assert price.amount == 89.0


def test_fx_unknown_currency_passthrough() -> None:
    assert convert_to_base(10.0, "XYZ", "AED") == 10.0


def test_parse_rating() -> None:
    assert parse_rating("4.5 out of 5 stars") == 4.5
    assert parse_rating("Rated 4.2/5 by shoppers") == 4.2
    assert parse_rating("no score here") is None


def test_extract_from_json_ld_product() -> None:
    html = """
    <html><head><title>Ignore me</title>
    <script type="application/ld+json">
    {
      "@type": "Product",
      "name": "SoundPeat Wireless Earbuds",
      "description": "Bluetooth 5.3 earbuds with ANC and 40h battery.",
      "offers": {"@type": "Offer", "price": "149.00", "priceCurrency": "AED"},
      "aggregateRating": {"ratingValue": "4.4", "reviewCount": "128"}
    }
    </script>
    </head><body><p>Also listed at AED 149</p></body></html>
    """
    item = extract_from_html(html, "https://noon.com/earbuds", "snippet", AppConfig())
    assert item.title == "SoundPeat Wireless Earbuds"
    assert item.price is not None
    assert item.price.amount == 149.0
    assert item.price.currency == "AED"
    assert item.rating == 4.4
    assert item.review_count == 128
    assert item.scrape_ok is True
