from search import domain_from_url, is_skippable_url


def test_domain_from_url_strips_www() -> None:
    assert domain_from_url("https://www.amazon.ae/dp/B0TEST") == "amazon.ae"


def test_skips_search_and_social() -> None:
    assert is_skippable_url("https://www.google.com/search?q=earbuds")
    assert is_skippable_url("https://youtube.com/watch?v=abc")
    assert is_skippable_url("https://example.com/spec.pdf")
    assert not is_skippable_url("https://www.noon.com/uae-en/earbuds")
