"""HTTP fetching plus HTML parsing for product title, price, rating, and features."""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any, Optional
import requests
from bs4 import BeautifulSoup, Tag

from config import AppConfig, PLAUSIBLE_PRICE_RANGE, convert_to_base
from models import PriceInfo, ProductItem, SearchResult
from querying import hit_is_plausible, missing_hard_required, missing_required, prefer_query_aware_title
from search import domain_from_url, looks_like_category_url, looks_like_product_url

logger = logging.getLogger(__name__)

CURRENCY_ALIASES: dict[str, str] = {
    "AED": "AED",
    "DHS": "AED",
    "DH": "AED",
    "د.إ": "AED",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "INR": "INR",
    "RS": "INR",
    "RS.": "INR",
    "₹": "INR",
    "SAR": "SAR",
    "SR": "SAR",
    "QAR": "QAR",
    "QR": "QAR",
    "KWD": "KWD",
    "BHD": "BHD",
    "OMR": "OMR",
    "EGP": "EGP",
    "PKR": "PKR",
    "CAD": "CAD",
    "C$": "CAD",
    "AUD": "AUD",
    "A$": "AUD",
    "JPY": "JPY",
    "¥": "JPY",
    "CNY": "CNY",
    "CHF": "CHF",
}

# Number that may include thousands separators, then a currency token.
_AMOUNT = r"(?P<amount>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_CODE = r"(?P<currency>AED|USD|EUR|GBP|INR|SAR|QAR|KWD|BHD|OMR|EGP|PKR|CAD|AUD|JPY|CNY|CHF|Dhs|DH|Rs\.?|SR|QR)"
_SYMBOL = r"(?P<symbol>[$€£₹¥]|د\.إ)"

PRICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"{_CODE}\s*{_AMOUNT}", re.IGNORECASE),
    re.compile(rf"{_AMOUNT}\s*{_CODE}", re.IGNORECASE),
    re.compile(rf"{_SYMBOL}\s*{_AMOUNT}"),
    re.compile(rf"{_AMOUNT}\s*{_SYMBOL}"),
)

RATING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?P<rating>\d(?:[.,]\d)?)\s*(?:out of|/)\s*(?P<scale>[5])", re.I),
    re.compile(r"(?P<rating>\d(?:[.,]\d)?)\s*(?:stars?)", re.I),
    re.compile(r"rating[\"'\s:=]+(?P<rating>\d(?:[.,]\d)?)", re.I),
)

JSON_LD_PRODUCT_TYPES = {"product", "productgroup", "individualproduct", "offer"}


def parse_amount(raw: str) -> Optional[float]:
    """Parse a numeric price string such as ``1,299.50`` or ``1.299,50``."""
    text = raw.strip()
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(",") == 1 and len(text.split(",")[-1]) in {1, 2}:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def normalize_currency(token: str) -> Optional[str]:
    """Map a symbol or code to an ISO-like currency code."""
    key = token.strip().upper()
    if key in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[key]
    if token.strip() in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[token.strip()]
    return CURRENCY_ALIASES.get(key.replace(" ", ""))


_BUDGET_PREFIX = re.compile(
    r"(?:under|below|less\s+than|up\s*to|upto|cheaper\s+than|<)\s*$",
    re.IGNORECASE,
)


def _is_budget_context(text: str, start: int) -> bool:
    """True when the match is a query-style cap such as “under 200 AED”, not a listing price."""
    prefix = text[max(0, start - 28) : start]
    return bool(_BUDGET_PREFIX.search(prefix))


def is_plausible_price(amount: float, currency: str) -> bool:
    """Reject years, crumbs, and amounts outside a per-currency sanity band."""
    if amount <= 0:
        return False
    if amount == int(amount) and 1990 <= amount <= 2035:
        return False
    lo, hi = PLAUSIBLE_PRICE_RANGE.get(currency.upper(), (1.0, 10_000_000.0))
    return lo <= amount <= hi


def parse_price(
    text: str,
    default_currency: str = "AED",
    base_currency: str = "AED",
) -> Optional[PriceInfo]:
    """Extract the first plausible price from free text."""
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text)
    for pattern in PRICE_PATTERNS:
        for match in pattern.finditer(compact):
            if _is_budget_context(compact, match.start()):
                continue
            amount = parse_amount(match.group("amount"))
            if amount is None:
                continue
            token = match.groupdict().get("currency") or match.groupdict().get("symbol") or ""
            currency = normalize_currency(token) or default_currency
            if not is_plausible_price(amount, currency):
                continue
            return PriceInfo(
                amount=amount,
                currency=currency,
                original_text=match.group(0).strip(),
                amount_base=convert_to_base(amount, currency, base_currency),
            )
    return None


def parse_rating(text: str, scale: float = 5.0) -> Optional[float]:
    """Extract a star/review score and normalize it to ``scale`` (usually 5)."""
    if not text:
        return None
    for pattern in RATING_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            value = float(match.group("rating").replace(",", "."))
        except (ValueError, AttributeError):
            continue
        found_scale = match.groupdict().get("scale")
        if found_scale:
            try:
                value = value / float(found_scale) * scale
            except ValueError:
                pass
        if 0 < value <= scale:
            return round(value, 2)
    return None


def _json_ld_blocks(soup: BeautifulSoup) -> list[Any]:
    blocks: list[Any] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.extend(data)
        elif isinstance(data, dict) and "@graph" in data:
            graph = data["@graph"]
            if isinstance(graph, list):
                blocks.extend(graph)
            else:
                blocks.append(graph)
        else:
            blocks.append(data)
    return blocks


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _type_names(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type") or node.get("type") or ""
    names = _as_list(raw)
    return {str(name).lower() for name in names}


def _looks_like_product(node: dict[str, Any]) -> bool:
    types = _type_names(node)
    return bool(types & JSON_LD_PRODUCT_TYPES) or "offers" in node


def extract_from_json_ld(
    soup: BeautifulSoup,
    default_currency: str,
    base_currency: str,
) -> dict[str, Any]:
    """Pull name, description, price, rating, and features from Product JSON-LD."""
    found: dict[str, Any] = {}
    for node in _json_ld_blocks(soup):
        if not isinstance(node, dict) or not _looks_like_product(node):
            continue
        if "name" in node and not found.get("title"):
            found["title"] = str(node["name"]).strip()
        if "description" in node and not found.get("description"):
            found["description"] = str(node["description"]).strip()

        offers = _as_list(node.get("offers"))
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            price_raw = offer.get("price") or offer.get("lowPrice")
            currency = str(offer.get("priceCurrency") or default_currency)
            if price_raw is not None and "price" not in found:
                amount = parse_amount(str(price_raw))
                code = normalize_currency(currency) or default_currency
                if amount is not None and is_plausible_price(amount, code):
                    found["price"] = PriceInfo(
                        amount=amount,
                        currency=code,
                        original_text=f"{price_raw} {currency}",
                        amount_base=convert_to_base(amount, code, base_currency),
                    )
            break

        rating_node = node.get("aggregateRating")
        if isinstance(rating_node, dict) and "rating" not in found:
            value = rating_node.get("ratingValue")
            best = rating_node.get("bestRating") or 5
            count = rating_node.get("reviewCount") or rating_node.get("ratingCount")
            if value is not None:
                try:
                    numeric = float(str(value).replace(",", "."))
                    scale = float(str(best).replace(",", ".")) or 5.0
                    found["rating"] = round(numeric / scale * 5.0, 2) if scale != 5 else round(numeric, 2)
                except ValueError:
                    pass
            if count is not None:
                try:
                    found["review_count"] = int(str(count).replace(",", ""))
                except ValueError:
                    pass

        extras = node.get("additionalProperty") or node.get("featureList")
        features: list[str] = []
        for extra in _as_list(extras):
            if isinstance(extra, dict):
                name = extra.get("name") or extra.get("propertyID")
                val = extra.get("value")
                if name and val:
                    features.append(f"{name}: {val}")
                elif val:
                    features.append(str(val))
            elif extra:
                features.append(str(extra))
        if features and "features" not in found:
            found["features"] = features[:8]
        if found.get("title") and (found.get("price") or found.get("rating")):
            break
    return found


def _meta(soup: BeautifulSoup, *keys: str) -> Optional[str]:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        if isinstance(tag, Tag):
            content = tag.get("content")
            if content:
                return str(content).strip()
    return None


def _itemprop(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find(attrs={"itemprop": prop})
    if not isinstance(tag, Tag):
        return None
    content = tag.get("content") or tag.get_text(" ", strip=True)
    return str(content).strip() if content else None


def extract_features(soup: BeautifulSoup, limit: int = 6) -> list[str]:
    """Collect short bullet-like features from common product-page lists."""
    features: list[str] = []
    selectors = [
        "#feature-bullets li",
        "[data-testid='product-features'] li",
        ".product-highlights li",
        ".a-unordered-list.a-vertical li",
        "ul.features li",
    ]
    for selector in selectors:
        for li in soup.select(selector):
            text = li.get_text(" ", strip=True)
            if text and 8 <= len(text) <= 180:
                features.append(text)
            if len(features) >= limit:
                return features
    if features:
        return features[:limit]
    return []


def extract_from_html(
    html: str,
    url: str,
    snippet: str,
    config: AppConfig,
    search_title: str = "",
) -> ProductItem:
    """Build a ``ProductItem`` from page HTML, falling back to the search snippet."""
    soup = BeautifulSoup(html, "lxml")
    json_ld = extract_from_json_ld(soup, config.base_currency, config.base_currency)

    title = (
        json_ld.get("title")
        or _meta(soup, "og:title", "twitter:title")
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
        or search_title
        or url
    )
    description = (
        json_ld.get("description")
        or _meta(soup, "og:description", "description", "twitter:description")
        or snippet
        or ""
    )
    features = json_ld.get("features") or extract_features(soup)
    if not features and description:
        features = [chunk.strip() for chunk in re.split(r"[•|;]", description) if chunk.strip()][:5]

    price: Optional[PriceInfo] = json_ld.get("price")
    if price is None:
        for candidate in (
            _meta(soup, "product:price:amount", "og:price:amount"),
            _itemprop(soup, "price"),
        ):
            if candidate:
                amount = parse_amount(candidate)
                currency = (
                    _meta(soup, "product:price:currency", "og:price:currency")
                    or config.base_currency
                )
                if amount is not None:
                    code = normalize_currency(currency) or config.base_currency
                    if is_plausible_price(amount, code):
                        price = PriceInfo(
                            amount=amount,
                            currency=code,
                            original_text=f"{candidate} {code}",
                            amount_base=convert_to_base(amount, code, config.base_currency),
                        )
                        break
    if price is None:
        visible = soup.get_text(" ", strip=True)[:8000]
        price = parse_price(visible, config.base_currency, config.base_currency)
    if price is None:
        price = parse_price(
            f"{search_title} {snippet} {title} {description}",
            config.base_currency,
            config.base_currency,
        )

    rating: Optional[float] = json_ld.get("rating")
    if rating is None:
        rating_text = _itemprop(soup, "ratingValue") or _meta(soup, "rating")
        if rating_text:
            try:
                rating = float(str(rating_text).replace(",", "."))
            except ValueError:
                rating = parse_rating(str(rating_text))
    if rating is None:
        rating = parse_rating(f"{snippet} {soup.get_text(' ', strip=True)[:4000]}")

    review_count = json_ld.get("review_count")
    if review_count is None:
        count_text = _itemprop(soup, "reviewCount") or _itemprop(soup, "ratingCount")
        if count_text:
            digits = re.sub(r"[^\d]", "", count_text)
            if digits:
                review_count = int(digits)

    return ProductItem(
        title=re.sub(r"\s+", " ", str(title)).strip(),
        url=url,
        source_domain=domain_from_url(url),
        description=re.sub(r"\s+", " ", str(description)).strip(),
        features=features,
        price=price,
        rating=rating,
        review_count=review_count,
        scrape_ok=True,
    )


class PageScraper:
    """Fetch product pages with timeouts, retries, and polite delays."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            }
        )

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": random.choice(self.config.user_agents)}

    def fetch(self, url: str) -> tuple[Optional[str], Optional[str]]:
        """Return ``(html, error)``. ``html`` is None on failure."""
        last_error: Optional[str] = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    timeout=self.config.request_timeout,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                    if response.status_code in {429, 503} and attempt < self.config.max_retries:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    return None, last_error
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    if not response.text.lstrip().startswith(("<!", "<html", "<HTML")):
                        return None, f"non-HTML content-type: {content_type or 'unknown'}"
                return response.text, None
            except requests.Timeout:
                last_error = "timeout"
            except requests.RequestException as exc:
                last_error = f"request failed: {exc.__class__.__name__}"
            if attempt < self.config.max_retries:
                time.sleep(0.6 * (attempt + 1))
        return None, last_error or "request failed"

    def scrape_one(self, hit: SearchResult, query: str = "") -> ProductItem:
        """Scrape a search hit, falling back to snippet-only data on errors."""
        html, error = self.fetch(hit.url)
        if html:
            try:
                item = extract_from_html(
                    html,
                    hit.url,
                    hit.snippet,
                    self.config,
                    search_title=hit.title,
                )
                if not item.title:
                    item.title = hit.title
                if query:
                    item.title = prefer_query_aware_title(query, item.title, hit.title)
                    if missing_required(query, f"{item.title} {item.description}") and (
                        not missing_hard_required(query, hit.title)
                    ):
                        item.description = f"{hit.title}. {item.description}".strip()
                if not item.description:
                    item.description = hit.snippet
                return item
            except Exception as exc:  # noqa: BLE001 — page HTML is untrusted
                logger.warning("Parse failed for %s: %s", hit.url, exc)
                error = f"parse failed: {exc.__class__.__name__}"
        fallback_price = parse_price(
            f"{hit.title} {hit.snippet}",
            self.config.base_currency,
            self.config.base_currency,
        )
        fallback_rating = parse_rating(f"{hit.title} {hit.snippet}")
        return ProductItem(
            title=hit.title,
            url=hit.url,
            source_domain=hit.source_domain or domain_from_url(hit.url),
            description=hit.snippet,
            price=fallback_price,
            rating=fallback_rating,
            scrape_ok=False,
            error=error,
        )

    def scrape_many(self, hits: list[SearchResult], query: str = "") -> list[ProductItem]:
        """Scrape up to ``max_pages`` product pages, skipping shop indexes."""
        items: list[ProductItem] = []
        product_hits = [hit for hit in hits if not looks_like_category_url(hit.url)]
        if len(product_hits) < 3:
            product_hits = list(hits)
        if query:
            plausible = [
                hit
                for hit in product_hits
                if hit_is_plausible(query, hit.title, hit.snippet, hit.url)
            ]
            if len(plausible) >= 3:
                product_hits = plausible
            product_hits.sort(
                key=lambda hit: (
                    not hit_is_plausible(query, hit.title, hit.snippet, hit.url),
                    len(missing_required(query, f"{hit.title} {hit.url}")),
                )
            )
        limit = min(len(product_hits), self.config.max_pages)
        for index, hit in enumerate(product_hits[:limit]):
            logger.info("Scraping %d/%d %s", index + 1, limit, hit.url)
            items.append(self.scrape_one(hit, query=query))
            if index < limit - 1:
                delay = random.uniform(self.config.min_delay_s, self.config.max_delay_s)
                time.sleep(delay)
        return items


def items_from_hits(query: str, hits: list[SearchResult], config: AppConfig) -> list[ProductItem]:
    """Turn search snippets into products so ranking can start before a scrape."""
    items: list[ProductItem] = []
    for hit in hits:
        if looks_like_category_url(hit.url) and not looks_like_product_url(hit.url):
            continue
        if not hit_is_plausible(query, hit.title, hit.snippet, hit.url):
            continue
        blob = f"{hit.title} {hit.snippet}"
        items.append(
            ProductItem(
                title=hit.title,
                url=hit.url,
                source_domain=hit.source_domain or domain_from_url(hit.url),
                description=hit.snippet,
                price=parse_price(blob, config.base_currency, config.base_currency),
                rating=parse_rating(blob),
                scrape_ok=False,
            )
        )
    return items


