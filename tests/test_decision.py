"""The buy: one listing, evidence checks, and the tradeoff on every other row."""

from __future__ import annotations

from config import AppConfig
from decision import build_decision
from models import LabeledPick, PriceInfo, ProductItem, RankedPicks
from scoring import rank_items


def _item(
    title: str,
    url: str,
    domain: str,
    amount: float | None,
    rating: float | None,
    description: str = "wireless earbuds",
    reviews: int | None = None,
) -> ProductItem:
    price = None
    if amount is not None:
        price = PriceInfo(amount=amount, currency="AED", original_text=str(amount), amount_base=amount)
    return ProductItem(
        title=title,
        url=url,
        source_domain=domain,
        description=description,
        price=price,
        rating=rating,
        review_count=reviews,
    )


def test_rank_items_names_a_buy_and_tradeoffs() -> None:
    config = AppConfig()
    items = [
        _item("Wireless Earbuds Pro", "https://noon.com/pro", "noon.com", 180, 4.6, reviews=128),
        _item("Wireless Earbuds Lite", "https://amazon.ae/lite", "amazon.ae", 99, 3.9, reviews=40),
        _item("Wireless Earbuds Flagship", "https://amazon.ae/flag", "amazon.ae", 199, 4.9, reviews=80),
        _item("Wireless Earbuds Mid", "https://noon.com/mid", "noon.com", 140, 4.2, reviews=30),
        _item("Wireless Earbuds Mini", "https://noon.com/mini", "noon.com", 120, 4.0, reviews=22),
    ]
    picks = rank_items(items, "wireless earbuds under 200 AED", config)
    verdict = picks.decision["verdict"]
    assert verdict["pick_id"] == "best_overall"
    assert verdict["url"] == picks.best_overall.url
    assert "AED" in verdict["price_display"]
    statuses = {check["id"]: check["status"] for check in picks.decision["checks"]}
    assert statuses["price"] == "pass"
    assert statuses["rating"] == "pass"
    assert statuses["reviews"] == "pass"
    assert statuses["delivery"] == "pass"
    assert statuses["budget"] == "pass"
    assert len(picks.decision["rows"]) == 5
    buy_rows = [row for row in picks.decision["rows"] if row["is_buy"]]
    assert len(buy_rows) == 1
    others = [row for row in picks.decision["rows"] if not row["is_buy"]]
    assert others
    assert any("AED" in row["edge"] for row in others)


def test_cheapest_query_buys_the_low_price() -> None:
    config = AppConfig()
    items = [
        _item("Wireless Earbuds Pro", "https://noon.com/pro", "noon.com", 180, 4.8, reviews=200),
        _item("Wireless Earbuds Lite", "https://amazon.ae/lite", "amazon.ae", 99, 4.0, reviews=50),
    ]
    picks = rank_items(items, "cheapest wireless earbuds", config)
    assert picks.decision["verdict"]["pick_id"] == "best_price"
    assert picks.decision["verdict"]["url"] == picks.best_price.url
    assert "lowest price" in picks.decision["verdict"]["reason"]


def test_missing_rating_is_a_warning_not_a_real_score() -> None:
    config = AppConfig()
    picks = rank_items(
        [_item("Wireless Earbuds", "https://noon.com/x", "noon.com", 120, None)],
        "wireless earbuds",
        config,
    )
    statuses = {check["id"]: check["status"] for check in picks.decision["checks"]}
    assert statuses["rating"] == "warn"
    assert statuses["reviews"] == "warn"
    assert "did not show a star rating" in picks.decision["verdict"]["reason"]
    assert picks.decision["hold"] == ""


def test_missing_price_holds_the_buy() -> None:
    config = AppConfig()
    picks = rank_items(
        [_item("Wireless Earbuds", "https://noon.com/x", "noon.com", None, 4.4, reviews=30)],
        "wireless earbuds",
        config,
    )
    assert picks.decision["hold"] == "Price is not on the page"
    assert any(check["status"] == "fail" and check["id"] == "price" for check in picks.decision["checks"])


def test_near_identical_title_calls_out_the_cheaper_store() -> None:
    config = AppConfig()
    items = [
        _item("Sony WH-1000XM5 Headphones", "https://noon.com/xm5", "noon.com", 1299, 4.6, "headphones", 400),
        _item("Sony WH-1000XM5 Headphones", "https://amazon.ae/xm5", "amazon.ae", 999, 4.5, "headphones", 220),
    ]
    picks = rank_items(items, "sony wh-1000xm5 headphones", config)
    note = picks.decision["same_title"]
    assert "near-identical title" in note
    assert "AED" in note
    buy_url = picks.decision["verdict"]["url"]
    if buy_url.endswith("noon.com/xm5"):
        assert "amazon.ae" in note
        assert "less" in note
    else:
        assert "noon.com" in note
        assert "more" in note


def test_empty_shortlist_has_no_verdict() -> None:
    picks = RankedPicks(query="wireless earbuds", base_currency="AED", items=[])
    assert build_decision(picks)["verdict"] is None


def test_hand_built_edge_states_the_savings() -> None:
    cheap = ProductItem(
        title="Lite",
        url="https://amazon.ae/lite",
        source_domain="amazon.ae",
        price=PriceInfo(99, "AED", "99", 99),
        rating=3.9,
        review_count=40,
        availability="local",
        availability_label="Sold in United Arab Emirates",
    )
    buy = ProductItem(
        title="Pro",
        url="https://noon.com/pro",
        source_domain="noon.com",
        price=PriceInfo(180, "AED", "180", 180),
        rating=4.6,
        review_count=128,
        availability="local",
        availability_label="Sold in United Arab Emirates",
    )
    picks = RankedPicks(
        query="wireless earbuds",
        base_currency="AED",
        country_name="United Arab Emirates",
        items=[buy, cheap],
        answers=[
            LabeledPick("best_overall", "Best match", "mix", buy),
            LabeledPick("best_price", "Best price", "cheap", cheap),
        ],
    )
    decision = build_decision(picks)
    price_row = next(row for row in decision["rows"] if row["id"] == "best_price")
    assert "Save 81 AED" in price_row["edge"]
    assert "0.7 stars lower" in price_row["edge"]
    assert "81 AED more" in decision["spread"]
