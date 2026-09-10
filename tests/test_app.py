from __future__ import annotations

from unittest.mock import patch

from config import AppConfig
from models import PriceInfo, ProductItem, RankedPicks, ScoreBreakdown
from search import EverywhereBackend, SearchBackend, SearchResult, build_search_backend


def test_index_renders_search_form() -> None:
    from app import app

    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "FindBest" in html
    assert 'id="search-form"' in html
    assert "wireless earbuds under 200 AED" in html


def test_search_requires_query() -> None:
    from app import app

    client = app.test_client()
    response = client.post("/api/search", json={"query": "   "})
    assert response.status_code == 400
    assert "query" in response.get_json()["error"].lower()


def test_search_returns_three_picks() -> None:
    from app import app

    item = ProductItem(
        title="Demo Wireless Earbuds",
        url="https://noon.com/demo",
        source_domain="noon.com",
        description="ANC earbuds",
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
    )
    with patch("app.run_pipeline", return_value=picks):
        client = app.test_client()
        response = client.post("/api/search", json={"query": "wireless earbuds under 200 AED"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["items_considered"] == 1
    labels = [pick["label"] for pick in payload["picks"]]
    assert labels == ["Best price", "Best match", "Best value"]
    assert payload["picks"][0]["item"]["title"] == "Demo Wireless Earbuds"


def test_everywhere_backend_is_selectable() -> None:
    config = AppConfig()
    config.search_backend = "everywhere"
    backend = build_search_backend(config)
    assert backend.name == "everywhere"


def test_everywhere_merges_and_dedupes() -> None:
    class Fake(SearchBackend):
        name = "fake"

        def __init__(self, rows: list[SearchResult]) -> None:
            self.rows = rows

        def search(self, query: str, max_results: int) -> list[SearchResult]:
            return self.rows[:max_results]

    shared = SearchResult("A", "https://amazon.ae/dp/1", "buds", "amazon.ae")
    extra = SearchResult("B", "https://noon.com/p/2", "buds", "noon.com")
    engine = EverywhereBackend("ae-en", timeout=5, serpapi_url="https://example.test")
    with patch.object(
        EverywhereBackend,
        "_backends",
        return_value=[Fake([shared, extra]), Fake([shared])],
    ):
        results = engine.search("wireless earbuds", 8)
    urls = [row.url for row in results]
    assert urls == ["https://amazon.ae/dp/1", "https://noon.com/p/2"]
