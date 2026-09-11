"""Scoring and category-ranking tests with synthetic products."""

from __future__ import annotations

from config import AppConfig, ScoreWeights
from models import PriceInfo, ProductItem
from scoring import budget_in_base, rank_items, relevance_score


def _item(
    title: str,
    url: str,
    domain: str,
    amount: float | None,
    rating: float | None,
    description: str = "",
    currency: str = "AED",
) -> ProductItem:
    price = None
    if amount is not None:
        price = PriceInfo(amount=amount, currency=currency, original_text=str(amount), amount_base=amount)
    return ProductItem(
        title=title,
        url=url,
        source_domain=domain,
        description=description,
        price=price,
        rating=rating,
    )


def test_relevance_prefers_title_matches() -> None:
    query = "wireless earbuds under 200 AED"
    good = _item(
        "Wireless Earbuds with ANC",
        "https://noon.com/a",
        "noon.com",
        150,
        4.5,
        "Bluetooth earbuds",
    )
    weak = _item(
        "HDMI cable 2m",
        "https://example.com/b",
        "example.com",
        20,
        5.0,
        "cable",
    )
    assert relevance_score(query, good) > relevance_score(query, weak)


def test_budget_in_base_aed() -> None:
    assert budget_in_base("wireless earbuds under 200 AED", "AED") == 200.0
    assert budget_in_base("best e scooter under 10k aed", "AED") == 10000.0
    assert budget_in_base("office chair under 10,000 AED", "AED") == 10000.0


def test_best_price_excludes_unknown_and_irrelevant() -> None:
    config = AppConfig()
    config.weights = ScoreWeights(relevance=0.45, price=0.25, rating=0.30).normalized()
    items = [
        _item("Wireless Earbuds Pro", "https://noon.com/pro", "noon.com", 180, 4.6, "wireless earbuds anc"),
        _item("Wireless Earbuds Lite", "https://amazon.ae/lite", "amazon.ae", 99, 3.9, "wireless earbuds"),
        _item("Wireless Earbuds Flagship", "https://amazon.ae/flag", "amazon.ae", 349, 4.9, "wireless earbuds"),
        _item("Random HDMI cable", "https://shop.example/hdmi", "shop.example", 15, 5.0, "cable"),
        _item("Wireless Earbuds no price", "https://reviews.example/buds", "reviews.example", None, 4.8, "wireless earbuds review"),
    ]
    picks = rank_items(items, "wireless earbuds under 200 AED", config)

    assert picks.best_price is not None
    assert picks.best_price.title == "Wireless Earbuds Lite"
    assert picks.best_price.price_base == 99

    assert picks.best_overall is not None
    # Flagship is expensive; lite/pro should compete on overall. The no-price
    # review should still be considered but not win Best price.
    assert picks.best_price.url != "https://reviews.example/buds"

    assert picks.best_value is not None
    assert picks.best_value.price_base is not None


def test_missing_rating_uses_neutral_default() -> None:
    config = AppConfig()
    item = _item("Wireless Earbuds", "https://noon.com/x", "noon.com", 120, None, "wireless earbuds")
    picks = rank_items([item], "wireless earbuds", config)
    scored = picks.items[0]
    assert scored.rating_is_default is True
    assert scored.rating == config.default_rating
    assert scored.scores.rating == round(config.default_rating / 5.0, 4)


def test_json_payload_contains_categories() -> None:
    config = AppConfig()
    items = [
        _item("Wireless Earbuds A", "https://a.example/a", "a.example", 100, 4.0, "wireless earbuds"),
        _item("Wireless Earbuds B", "https://b.example/b", "b.example", 140, 4.8, "wireless earbuds anc"),
    ]
    payload = rank_items(items, "wireless earbuds", config).to_dict()
    assert payload["items_considered"] == 2
    assert "best_price" in payload["categories"]
    assert "best_overall" in payload["categories"]
    assert "best_value" in payload["categories"]
    assert payload["categories"]["best_price"]["price"]["amount"] == 100
    assert "best_rated" in payload["categories"]
    assert "also_consider" in payload["categories"]
    assert 1 <= len(payload["answers"]) <= 5


def test_rank_items_returns_five_distinct_answers() -> None:
    config = AppConfig()
    items = [
        _item(f"Wireless Earbuds {n}", f"https://shop.example/{n}", "shop.example", 80 + n * 20, 3.5 + n * 0.3, "wireless earbuds")
        for n in range(6)
    ]
    picks = rank_items(items, "wireless earbuds", config)
    assert len(picks.answers) == 5
    urls = [pick.item.url for pick in picks.answers if pick.item]
    assert len(urls) == len(set(urls))
    labels = [pick.label for pick in picks.answers]
    assert "Best match" in labels
    assert "Best price" in labels
