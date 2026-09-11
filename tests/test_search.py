from search import (
    domain_from_url,
    is_skippable_url,
    looks_like_category_url,
    looks_like_product_url,
)


def test_domain_from_url_strips_www() -> None:
    assert domain_from_url("https://www.amazon.ae/dp/B0TEST") == "amazon.ae"


def test_skips_search_and_social() -> None:
    assert is_skippable_url("https://www.google.com/search?q=earbuds")
    assert is_skippable_url("https://youtube.com/watch?v=abc")
    assert is_skippable_url("https://example.com/spec.pdf")
    assert not is_skippable_url("https://www.noon.com/uae-en/earbuds")
    assert is_skippable_url("https://ar.aliexpress.com/w/wholesale-vsett-10-scooter.html")
    assert is_skippable_url("https://www.amazon.ae/s?rh=n:12285885031")
    assert is_skippable_url("https://www.amazon.ae/Electric-Scooters-Sport/s?rh=n:12285885031")
    assert is_skippable_url("https://www.reddit.com/r/dubai/comments/abc")


def test_product_url_heuristic() -> None:
    assert looks_like_product_url("https://www.amazon.ae/dp/B0ABCDEF")
    assert not looks_like_product_url("https://www.amazon.ae/s?k=earbuds")
    assert not looks_like_product_url(
        "https://www.gilanimobility.ae/product-category/electric-mobility-scooters/"
    )
    assert looks_like_category_url(
        "https://uae.sharafdg.com/c/toys_hobbies/electricscooters/"
    )
    assert looks_like_category_url("https://www.carrefouruae.com/mafuae/en/c/NF1440200")
    assert looks_like_category_url("https://dubaiscooters.ae/")
    assert looks_like_category_url("https://www.jumbo.ae/toys/scooters.html")
    assert looks_like_category_url(
        "https://www.amazon.ae/gp/bestsellers/sports-goods/12285885031"
    )
    assert looks_like_category_url("https://www.whizz.ae/brand/navee/")
    assert not looks_like_category_url("https://www.amazon.ae/dp/B0ABCDEF")
