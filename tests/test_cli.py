"""CLI wiring tests that do not hit the network."""

from __future__ import annotations

import json

from config import AppConfig
from main import apply_cli_overrides, build_parser, format_table
from models import PriceInfo, ProductItem, RankedPicks, ScoreBreakdown


def test_parser_accepts_weights_and_json() -> None:
    args = build_parser().parse_args(
        [
            "--query",
            "wireless earbuds under 200 AED",
            "--max-results",
            "8",
            "--base-currency",
            "USD",
            "--weights",
            '{"relevance":0.5,"price":0.2,"rating":0.3}',
            "--json",
        ]
    )
    config = apply_cli_overrides(AppConfig.from_env(), args)
    assert config.max_results == 8
    assert config.base_currency == "USD"
    assert abs(config.weights.relevance - 0.5) < 1e-9
    assert args.as_json is True


def test_format_table_includes_all_categories() -> None:
    item = ProductItem(
        title="Demo Wireless Earbuds",
        url="https://noon.com/demo",
        source_domain="noon.com",
        description="ANC earbuds with 30h battery",
        price=PriceInfo(amount=149, currency="AED", original_text="AED 149", amount_base=149),
        rating=4.4,
        scores=ScoreBreakdown(relevance=0.8, price=0.7, rating=0.88, overall=0.79, value=0.6),
    )
    picks = RankedPicks(
        query="wireless earbuds",
        base_currency="AED",
        items=[item],
        best_price=item,
        best_overall=item,
        best_value=item,
        weights={"relevance": 0.45, "price": 0.25, "rating": 0.30},
    )
    table = format_table(picks)
    assert "Best price" in table
    assert "Best overall match" in table or "Best match" in table
    assert "Best value" in table
    assert "noon.com" in table
    payload = json.dumps(picks.to_dict())
    assert "Demo Wireless Earbuds" in payload
