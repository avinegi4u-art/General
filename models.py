"""Dataclasses for search hits, parsed products, scores, and ranked picks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class SearchResult:
    """A single organic search hit before the product page is scraped."""

    title: str
    url: str
    snippet: str = ""
    source_domain: str = ""


@dataclass
class PriceInfo:
    """A parsed price plus an optional conversion into the configured base currency."""

    amount: float
    currency: str
    original_text: str
    amount_base: Optional[float] = None

    def format(self, base_currency: str | None = None) -> str:
        """Return a short human-readable price, including the base conversion when useful."""
        original = f"{self.amount:.2f} {self.currency}"
        if (
            self.amount_base is not None
            and base_currency
            and self.currency.upper() != base_currency.upper()
        ):
            return f"{original} (~{self.amount_base:.2f} {base_currency.upper()})"
        return original


@dataclass
class ScoreBreakdown:
    """Transparent 0–1 component scores and the weighted overall score."""

    relevance: float = 0.0
    price: float = 0.0
    rating: float = 0.0
    availability: float = 0.0
    overall: float = 0.0
    value: float = 0.0


@dataclass
class ProductItem:
    """A product (or review/listing page) after extraction and scoring."""

    title: str
    url: str
    source_domain: str
    description: str = ""
    features: list[str] = field(default_factory=list)
    price: Optional[PriceInfo] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    rating_is_default: bool = False
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    availability: str = "unknown"
    availability_label: str = ""
    scrape_ok: bool = False
    error: Optional[str] = None

    @property
    def price_base(self) -> Optional[float]:
        if self.price is None:
            return None
        return self.price.amount_base

    def short_description(self, max_len: int = 140) -> str:
        text = self.description.strip() or " ".join(self.features)
        text = " ".join(text.split())
        if len(text) <= max_len:
            return text
        return text[: max_len - 1].rstrip() + "…"

    def to_dict(self, base_currency: str = "AED") -> dict[str, Any]:
        """Serialize for JSON output."""
        payload = asdict(self)
        if self.price is not None:
            payload["price_display"] = self.price.format(base_currency)
        else:
            payload["price_display"] = None
        return payload


@dataclass
class LabeledPick:
    """One of the top answers shown in the UI or CLI table."""

    key: str
    label: str
    blurb: str
    item: Optional[ProductItem] = None

    def to_dict(self, base_currency: str = "AED") -> dict[str, Any]:
        return {
            "id": self.key,
            "label": self.label,
            "blurb": self.blurb,
            "item": self.item.to_dict(base_currency) if self.item else None,
        }


@dataclass
class RankedPicks:
    """The top answers plus the full scored catalogue."""

    query: str
    base_currency: str
    items: list[ProductItem]
    country_code: str = "AE"
    country_name: str = "United Arab Emirates"
    best_price: Optional[ProductItem] = None
    best_overall: Optional[ProductItem] = None
    best_value: Optional[ProductItem] = None
    best_rated: Optional[ProductItem] = None
    also_consider: Optional[ProductItem] = None
    answers: list[LabeledPick] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def item_or_none(item: Optional[ProductItem]) -> Optional[dict[str, Any]]:
            return item.to_dict(self.base_currency) if item else None

        return {
            "query": self.query,
            "base_currency": self.base_currency,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "weights": self.weights,
            "items_considered": len(self.items),
            "notes": self.notes,
            "categories": {
                "best_price": item_or_none(self.best_price),
                "best_overall": item_or_none(self.best_overall),
                "best_value": item_or_none(self.best_value),
                "best_rated": item_or_none(self.best_rated),
                "also_consider": item_or_none(self.also_consider),
            },
            "answers": [pick.to_dict(self.base_currency) for pick in self.answers],
            "items": [item.to_dict(self.base_currency) for item in self.items],
        }
