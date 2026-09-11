from search import (
    canonicalize_url,
    domain_from_url,
    is_skippable_url,
    looks_like_brand_collection_url,
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
    shopify_product = (
        "https://www.e-scooteruaehub.com/collections/vsett/products/"
        "vsett-10-apex-electric-scooter-60v-2-8ah-1500w-dual-motor"
    )
    assert looks_like_product_url(shopify_product)
    assert not looks_like_category_url(shopify_product)
    collection = "https://www.e-scooteruaehub.com/collections/vsett"
    assert looks_like_category_url(collection)
    assert looks_like_brand_collection_url(collection, "vsett scooter buy")
    assert not looks_like_brand_collection_url(shopify_product, "vsett scooter buy")
    tracked = (
        collection
        + "?srsltid=AfmBOop-QtEaZZE0NuUUd1gGn6pkz2XwQboG_R0CYIAJ4JYppQTDmQd5"
    )
    assert canonicalize_url(tracked) == collection
    nested = (
        "https://www.e-scooteruaehub.com/collections/vsett/products/"
        "vsett-8-electric-scooter"
    )
    assert (
        canonicalize_url(nested)
        == "https://www.e-scooteruaehub.com/products/vsett-8-electric-scooter"
    )


def test_vsett_collection_html_yields_product_listings() -> None:
    from scraper import product_hits_from_collection

    html = """
    <a href="/collections/vsett/products/vsett-8-electric-scooter">VSETT 8 Electric Scooter</a>
    <a href="/collections/vsett/products/vsett-10-apex-electric-scooter-60v">VSETT 10 APEX Electric Scooter</a>
    <a href="/collections/all">All products</a>
    """
    hits = product_hits_from_collection(
        html, "https://www.e-scooteruaehub.com/collections/vsett", "vsett scooter buy"
    )
    urls = [hit.url for hit in hits]
    assert any("vsett-8-electric-scooter" in url for url in urls)
    assert any("vsett-10-apex" in url for url in urls)
    assert all("/collections/all" not in url for url in urls)
