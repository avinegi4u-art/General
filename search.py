"""Search backends: DuckDuckGo, Google (CSE or library), and SerpAPI."""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable
from urllib.parse import urlparse

import requests

from config import PRODUCT_PATH_HINTS, SKIP_DOMAINS, SKIP_EXTENSIONS, AppConfig
from models import SearchResult

logger = logging.getLogger(__name__)


def domain_from_url(url: str) -> str:
    """Return a lowercase hostname without a leading ``www.``."""
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


_CATEGORY_LAST = frozenset(
    {
        "",
        "s",  # Amazon search: /s or /Electric-Scooters/s
        "b",
        "cycling",
        "scooters",
        "search",
        "classified",
        "category",
        "categories",
        "collections",
        "products",
        "deals",
        "shop",
        "store",
        "electric-scooters-hoverboards",
        "electric-scooters",
        "electricscooters",
        "e-scooters",
        "escooters",
        "sports-equipment",
        "sporting-goods",
        "hoverboards",
    }
)
_CATEGORY_MARKERS = (
    "/product-category/",
    "/product-tag/",
    "/collections/",
    "/categories/",
    "/category/",
    "/classified",
    "/gp/bestsellers",
    "/gp/best-sellers",
    "/brand/",
)


def looks_like_category_url(url: str) -> bool:
    """True for shop category, browse, and index pages — not a single listing."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    path_r = path.rstrip("/")
    last = path_r.rsplit("/", 1)[-1] if path_r else ""
    last = last.split(".")[0]
    if not path_r:
        return True
    if "product-category" in path or "product-tag" in path:
        return True
    if any(marker in path for marker in _CATEGORY_MARKERS):
        return True
    if last in _CATEGORY_LAST:
        return True
    # Carrefour /c/ID, Sharaf DG /c/toys_hobbies/...
    if re.search(r"/c/[\w-]+", path) and "/dp/" not in path:
        return True
    return False


def looks_like_product_url(url: str) -> bool:
    """Heuristic used to prefer marketplace/product URLs over category/search pages."""
    if looks_like_category_url(url):
        return False
    path = urlparse(url).path.lower()
    return any(hint in path for hint in PRODUCT_PATH_HINTS)


def is_skippable_url(url: str) -> bool:
    """True if the URL is a search/social page or a non-HTML asset."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return True
    host = domain_from_url(url)
    if not host:
        return True
    for skipped in SKIP_DOMAINS:
        if host == skipped or host.endswith("." + skipped):
            return True
    if "/search/" in path or path.rstrip("/").endswith("/search"):
        return True
    if path.rstrip("/").endswith("/s") or path.rstrip("/") == "/s":
        return True
    if "/w/wholesale" in path or "/wholesale-" in path:
        return True
    if "/wiki" in path or "/s/wiki" in path:
        return True
    return False


class SearchBackend(ABC):
    """Interface for a web search provider."""

    name: str = "base"

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return organic results for ``query``, capped at ``max_results``."""


class DuckDuckGoBackend(SearchBackend):
    """DuckDuckGo via the ``ddgs`` / ``duckduckgo_search`` library (no HTML scraping)."""

    name = "duckduckgo"

    def __init__(self, region: str = "ae-en") -> None:
        self.region = region

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        ddgs_cls = _load_ddgs()
        results: list[SearchResult] = []
        client = ddgs_cls()
        try:
            raw = list(client.text(query, region=self.region, max_results=max_results * 2) or [])
        finally:
            closer = getattr(client, "close", None)
            if callable(closer):
                closer()
        for row in raw:
            url = (row.get("href") or row.get("url") or "").strip()
            title = (row.get("title") or "").strip()
            snippet = (row.get("body") or row.get("snippet") or "").strip()
            if not url or is_skippable_url(url):
                continue
            results.append(
                SearchResult(
                    title=title or url,
                    url=url,
                    snippet=snippet,
                    source_domain=domain_from_url(url),
                )
            )
            if len(results) >= max_results:
                break
        return results


class GoogleLibraryBackend(SearchBackend):
    """Optional ``googlesearch-python`` backend.

    This library queries Google through a search helper rather than a hand-rolled
    HTML scraper. Prefer SerpAPI or Google Programmable Search when possible.
    """

    name = "google"

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            from googlesearch import search as google_search
        except ImportError as exc:
            raise RuntimeError(
                "googlesearch-python is not installed. pip install googlesearch-python"
            ) from exc

        results: list[SearchResult] = []
        hits: Iterable[object]
        try:
            hits = google_search(query, num_results=max_results * 2, advanced=True)
        except TypeError:
            hits = google_search(query, num_results=max_results * 2)

        for hit in hits:
            if isinstance(hit, str):
                url, title, snippet = hit, hit, ""
            else:
                url = getattr(hit, "url", "") or getattr(hit, "link", "") or ""
                title = getattr(hit, "title", "") or url
                snippet = getattr(hit, "description", "") or getattr(hit, "snippet", "") or ""
            url = str(url).strip()
            if not url or is_skippable_url(url):
                continue
            results.append(
                SearchResult(
                    title=str(title).strip() or url,
                    url=url,
                    snippet=str(snippet).strip(),
                    source_domain=domain_from_url(url),
                )
            )
            if len(results) >= max_results:
                break
        return results


class GoogleCseBackend(SearchBackend):
    """Official Google Programmable Search (Custom Search JSON API)."""

    name = "google_cse"

    def __init__(
        self,
        api_key: str,
        cse_id: str,
        timeout: float,
        gl: str = "ae",
        hl: str = "en",
    ) -> None:
        self.api_key = api_key
        self.cse_id = cse_id
        self.timeout = timeout
        self.gl = gl
        self.hl = hl

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(max_results, 10),
            "gl": self.gl,
            "hl": self.hl,
        }
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        results: list[SearchResult] = []
        for row in payload.get("items", []):
            url = (row.get("link") or "").strip()
            if not url or is_skippable_url(url):
                continue
            results.append(
                SearchResult(
                    title=(row.get("title") or url).strip(),
                    url=url,
                    snippet=(row.get("snippet") or "").strip(),
                    source_domain=domain_from_url(url),
                )
            )
        return results[:max_results]


class SerpApiBackend(SearchBackend):
    """SerpAPI Google engine — compliant third-party SERP API."""

    name = "serpapi"

    def __init__(
        self,
        api_key: str,
        timeout: float,
        endpoint: str,
        gl: str = "ae",
        hl: str = "en",
        location: str = "United Arab Emirates",
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.endpoint = endpoint
        self.gl = gl
        self.hl = hl
        self.location = location

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.api_key,
            "num": min(max_results, 20),
            "gl": self.gl,
            "hl": self.hl,
            "location": self.location,
        }
        response = requests.get(self.endpoint, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        results: list[SearchResult] = []
        for row in payload.get("organic_results", []):
            url = (row.get("link") or "").strip()
            if not url or is_skippable_url(url):
                continue
            results.append(
                SearchResult(
                    title=(row.get("title") or url).strip(),
                    url=url,
                    snippet=(row.get("snippet") or "").strip(),
                    source_domain=domain_from_url(url),
                )
            )
            if len(results) >= max_results:
                break
        return results


class EverywhereBackend(SearchBackend):
    """Fan out across DuckDuckGo (multi-engine web) plus Google when available.

    DuckDuckGo's ``ddgs`` client already queries several web indexes. This
    backend merges those hits with SerpAPI / Google CSE when keys are set,
    or with ``googlesearch-python`` otherwise, then de-duplicates URLs.
    """

    name = "everywhere"

    def __init__(
        self,
        region: str,
        timeout: float,
        serpapi_url: str,
        gl: str = "ae",
        hl: str = "en",
        location: str = "United Arab Emirates",
    ) -> None:
        self.region = region
        self.timeout = timeout
        self.serpapi_url = serpapi_url
        self.gl = gl
        self.hl = hl
        self.location = location

    def _backends(self) -> list[SearchBackend]:
        backends: list[SearchBackend] = [DuckDuckGoBackend(self.region)]
        serp_key = os.getenv("SERPAPI_KEY", "").strip()
        if serp_key:
            backends.append(
                SerpApiBackend(
                    serp_key,
                    self.timeout,
                    self.serpapi_url,
                    gl=self.gl,
                    hl=self.hl,
                    location=self.location,
                )
            )
        google_key = os.getenv("GOOGLE_API_KEY", "").strip()
        cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        if google_key and cse_id:
            backends.append(
                GoogleCseBackend(google_key, cse_id, self.timeout, gl=self.gl, hl=self.hl)
            )
        return backends

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        backends = self._backends()
        merged: list[SearchResult] = []
        seen: set[str] = set()
        per_backend = max(max_results, 8)

        def run_one(backend: SearchBackend) -> list[SearchResult]:
            try:
                logger.info("everywhere: querying %s", backend.name)
                return backend.search(query, per_backend)
            except Exception as exc:  # noqa: BLE001 — a single engine must not fail the search
                logger.warning("everywhere: %s failed: %s", backend.name, exc)
                return []

        timeout = max(self.timeout + 8.0, 20.0)
        with ThreadPoolExecutor(max_workers=len(backends)) as pool:
            futures = [pool.submit(run_one, backend) for backend in backends]
            try:
                for future in as_completed(futures, timeout=timeout):
                    try:
                        hits = future.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("everywhere: worker failed: %s", exc)
                        continue
                    for hit in hits:
                        key = hit.url.split("#", 1)[0].rstrip("/")
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        merged.append(hit)
            except TimeoutError:
                logger.warning("everywhere: timed out waiting for some search engines")
        logger.info(
            "everywhere: merged %d unique hit(s) from %d engine(s)",
            len(merged),
            len(backends),
        )
        return merged


def _load_ddgs():  # type: ignore[no-untyped-def]
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # type: ignore[import-not-found]

            return DDGS
        except ImportError as exc:
            raise RuntimeError(
                "Neither 'ddgs' nor 'duckduckgo-search' is installed. "
                "pip install ddgs"
            ) from exc


def build_search_backend(config: AppConfig) -> SearchBackend:
    """Construct the backend named by ``SEARCH_BACKEND`` / ``config.search_backend``."""
    name = config.search_backend.lower().strip()
    if name in {"duckduckgo", "ddg", "ddgs"}:
        return DuckDuckGoBackend(region=config.search_region)
    if name in {"everywhere", "all", "web"}:
        return EverywhereBackend(
            region=config.search_region,
            timeout=config.request_timeout,
            serpapi_url=config.serpapi_url,
            gl=config.google_gl,
            hl=config.google_hl,
            location=config.google_location,
        )
    if name in {"serpapi", "serp"}:
        api_key = os.getenv("SERPAPI_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SEARCH_BACKEND=serpapi requires SERPAPI_KEY.")
        return SerpApiBackend(
            api_key,
            config.request_timeout,
            config.serpapi_url,
            gl=config.google_gl,
            hl=config.google_hl,
            location=config.google_location,
        )
    if name in {"google_cse", "cse"}:
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        if not api_key or not cse_id:
            raise RuntimeError(
                "SEARCH_BACKEND=google_cse requires GOOGLE_API_KEY and GOOGLE_CSE_ID."
            )
        return GoogleCseBackend(
            api_key, cse_id, config.request_timeout, gl=config.google_gl, hl=config.google_hl
        )
    if name in {"google", "googlesearch"}:
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        if api_key and cse_id:
            logger.info("GOOGLE_API_KEY detected; using Programmable Search JSON API.")
            return GoogleCseBackend(
                api_key, cse_id, config.request_timeout, gl=config.google_gl, hl=config.google_hl
            )
        logger.warning(
            "Using googlesearch-python. Prefer SERPAPI_KEY or GOOGLE_CSE_ID for a "
            "ToS-friendly Google search."
        )
        return GoogleLibraryBackend()
    raise RuntimeError(
        f"Unknown SEARCH_BACKEND={name!r}. "
        "Use duckduckgo, everywhere, google, google_cse, or serpapi."
    )


def _merge_hits(groups: Iterable[list[SearchResult]]) -> list[SearchResult]:
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for group in groups:
        for hit in group:
            key = hit.url.split("#", 1)[0].rstrip("/")
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(hit)
    return unique


def search_marketplace_sites(query: str, config: AppConfig) -> list[SearchResult]:
    """Fan out site-restricted searches so local stores are not missed."""
    from location import get_country, marketplace_site_queries
    from querying import product_core_query, required_terms, shopping_followup_queries

    country = get_country(config.country_code)
    # Negatives like -kit hide amazon.ae product pages. Site searches use brand+model only.
    core = product_core_query(query)
    queries = marketplace_site_queries(core, country)
    req = required_terms(query)
    if req and country.local_domains:
        queries.insert(0, f'"{" ".join(req)}" site:{country.local_domains[0]}')
    queries.extend(shopping_followup_queries(query, country.search_terms[0]))
    if not queries:
        return []
    ddg = DuckDuckGoBackend(region=config.search_region)
    per_query = 5

    def run_one(site_query: str) -> list[SearchResult]:
        try:
            logger.info("marketplace search: %r", site_query)
            return ddg.search(site_query, per_query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("marketplace search failed for %r: %s", site_query, exc)
            return []

    extra: list[SearchResult] = []
    primary: list[str] = []
    rest = list(queries)
    if req and country.local_domains:
        first = f'"{" ".join(req)}" site:{country.local_domains[0]}'
        rest = [row for row in queries if row != first]
        primary.append(first)

    for site_query in primary:
        rows = run_one(site_query)
        extra.extend(rows)
        has_product = any(looks_like_product_url(hit.url) for hit in rows)
        if not has_product:
            extra.extend(run_one(site_query))

    if rest:
        with ThreadPoolExecutor(max_workers=min(4, len(rest))) as pool:
            futures = [pool.submit(run_one, site_query) for site_query in rest]
            try:
                for future in as_completed(futures, timeout=max(config.request_timeout + 6.0, 18.0)):
                    try:
                        extra.extend(future.result())
                    except Exception as worker_err:  # noqa: BLE001
                        logger.warning("marketplace worker failed: %s", worker_err)
            except TimeoutError:
                logger.warning("marketplace searches timed out")
    return extra


def search_web(query: str, config: AppConfig) -> list[SearchResult]:
    """Run a search and return unique, scrape-eligible results.

    The open-web query is localized to the shopper's country. Additional
    site-restricted searches pull in local stores and sellers that ship there
    (for example AliExpress) so those listings are not crowded out by
    another country's storefronts.
    """
    from location import classify_listing, get_country, localize_query
    from querying import (
        expand_shopper_query,
        hit_is_plausible,
        missing_required,
        precise_search_query,
        product_core_query,
        required_terms,
    )

    country = get_country(config.country_code)
    # Brand searches: skip the long -mudguard list. DDG often returns nothing for it.
    focused = product_core_query(query) if required_terms(query) else precise_search_query(query)
    localized = localize_query(focused, country)
    backend = build_search_backend(config)
    logger.info(
        "Searching with backend=%s country=%s query=%r localized=%r",
        backend.name,
        country.code,
        query,
        localized,
    )
    hits: list[SearchResult] = []
    try:
        hits = backend.search(localized, max(config.max_results * 2, config.max_pages))
    except Exception:
        logger.exception("Search backend %s failed", backend.name)

    extra: list[SearchResult] = []
    try:
        extra = search_marketplace_sites(query, config)
    except Exception as exc:  # noqa: BLE001 — extras must not fail the whole search
        logger.warning("marketplace searches failed: %s", exc)

    unique = _merge_hits([hits, extra])
    if len(unique) < 8:
        try:
            expanded = expand_shopper_query(query)
            logger.info("Few hits; retrying with the expanded query %r", expanded)
            retry = backend.search(
                localize_query(expanded, country),
                max(config.max_results, 8),
            )
            unique = _merge_hits([unique, retry])
        except Exception as retry_exc:  # noqa: BLE001
            logger.warning("fallback search failed: %s", retry_exc)

    unique.sort(
        key=lambda hit: (
            not hit_is_plausible(query, hit.title, hit.snippet, hit.url),
            len(missing_required(query, f"{hit.title} {hit.url}")),
            not looks_like_product_url(hit.url),
            looks_like_category_url(hit.url),
            {"local": 0, "ships": 1, "unknown": 2, "foreign": 3}[
                classify_listing(hit.url, hit.source_domain, country).kind
            ],
        )
    )
    buyable_n = sum(
        1
        for hit in unique
        if classify_listing(hit.url, hit.source_domain, country).kind in {"local", "ships"}
    )
    logger.info(
        "Search returned %d unique result(s) (%d local/ships) for %s",
        len(unique),
        buyable_n,
        country.code,
    )
    return unique[: config.max_results]
