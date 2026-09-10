"""Command-line entrypoint for the product search, scrape, and rank pipeline."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Optional, Sequence

from tabulate import tabulate

from config import AppConfig, parse_weights
from models import ProductItem, RankedPicks
from scraper import PageScraper
from scoring import rank_items
from search import search_web

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="product-finder",
        description=(
            "Search the web for products matching a query, scrape listing pages, "
            "and rank Best price / Best overall match / Best value."
        ),
    )
    parser.add_argument("--query", "-q", required=True, help="Natural-language product query.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Maximum search hits to collect (default from config/env).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum product pages to scrape (avoids over-fetching).",
    )
    parser.add_argument(
        "--base-currency",
        default=None,
        help="Currency used for price comparison (default AED).",
    )
    parser.add_argument(
        "--weights",
        default=None,
        help='JSON object of scoring weights, e.g. \'{"relevance":0.5,"price":0.2,"rating":0.3}\'.',
    )
    parser.add_argument(
        "--backend",
        default=None,
        help="Search backend: duckduckgo, google, google_cse, or serpapi.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print machine-readable JSON instead of (or in addition to) the table.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print JSON only; skip the CLI table.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging.")
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("primp").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    if verbose:
        for name in ("search", "scraper", "scoring", "main"):
            logging.getLogger(name).setLevel(logging.DEBUG)


def apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    if args.max_results is not None:
        config.max_results = max(1, args.max_results)
    if args.max_pages is not None:
        config.max_pages = max(1, args.max_pages)
    if args.base_currency:
        config.base_currency = args.base_currency.upper()
    if args.weights:
        config.weights = parse_weights(args.weights)
    if args.backend:
        config.search_backend = args.backend.lower()
    return config


def _price_cell(item: ProductItem, base_currency: str) -> str:
    if item.price is None:
        return "unknown"
    return item.price.format(base_currency)


def _rating_cell(item: ProductItem) -> str:
    if item.rating is None:
        return "—"
    marker = "*" if item.rating_is_default else ""
    count = f" ({item.review_count})" if item.review_count else ""
    return f"{item.rating:.1f}/5{marker}{count}"


def _truncate(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: width - 1].rstrip() + "…"


def format_table(picks: RankedPicks) -> str:
    """Pretty-print the three category winners as a terminal table."""
    rows = []
    categories = (
        ("Best price", picks.best_price),
        ("Best overall match", picks.best_overall),
        ("Best value", picks.best_value),
    )
    for label, item in categories:
        if item is None:
            rows.append([label, "—", "—", "—", "—", "—", "—"])
            continue
        rows.append(
            [
                label,
                _truncate(item.title, 48),
                item.source_domain,
                _price_cell(item, picks.base_currency),
                _rating_cell(item),
                f"{item.scores.overall:.2f}",
                _truncate(item.short_description(90), 90),
            ]
        )

    table = tabulate(
        rows,
        headers=["Category", "Title", "Source", "Price", "Rating", "Overall", "Why / summary"],
        tablefmt="github",
    )
    extra: list[str] = []
    extra.append(
        "\nScores: overall = w_rel·relevance + w_price·price + w_rating·rating "
        f"(weights {picks.weights}). Rating marked * used the neutral default."
    )
    extra.append(f"Items considered: {len(picks.items)}. Base currency: {picks.base_currency}.")
    if picks.notes:
        extra.append("Notes: " + " ".join(picks.notes))

    detail_rows = []
    for item in picks.items[:8]:
        detail_rows.append(
            [
                _truncate(item.title, 40),
                item.source_domain,
                _price_cell(item, picks.base_currency),
                _rating_cell(item),
                f"{item.scores.relevance:.2f}",
                f"{item.scores.price:.2f}",
                f"{item.scores.rating:.2f}",
                f"{item.scores.overall:.2f}",
                f"{item.scores.value:.2f}",
            ]
        )
    details = ""
    if detail_rows:
        details = "\n\nTop scraped results (by overall score):\n" + tabulate(
            detail_rows,
            headers=[
                "Title",
                "Source",
                "Price",
                "Rating",
                "Rel",
                "PriceS",
                "RateS",
                "Overall",
                "Value",
            ],
            tablefmt="github",
        )
    return table + "".join(f"\n{line}" for line in extra) + details


def run(query: str, config: AppConfig) -> RankedPicks:
    """Search → scrape → score → rank."""
    hits = search_web(query, config)
    if not hits:
        logger.warning("No search results for %r", query)
        return RankedPicks(
            query=query,
            base_currency=config.base_currency,
            items=[],
            notes=["Search returned no usable results."],
            weights={
                "relevance": config.weights.relevance,
                "price": config.weights.price,
                "rating": config.weights.rating,
            },
        )
    scraper = PageScraper(config)
    products = scraper.scrape_many(hits)
    return rank_items(products, query, config)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    config = apply_cli_overrides(AppConfig.from_env(), args)

    try:
        picks = run(args.query, config)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        logger.error("Run failed: %s", exc)
        return 1

    emit_table = not args.json_only
    emit_json = args.as_json or args.json_only
    if emit_table:
        print(format_table(picks))
        print()
        for label, item in (
            ("Best price", picks.best_price),
            ("Best overall match", picks.best_overall),
            ("Best value", picks.best_value),
        ):
            if item:
                print(f"{label} URL: {item.url}")
    if emit_json:
        if emit_table:
            print()
        print(json.dumps(picks.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
