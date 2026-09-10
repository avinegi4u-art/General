"""Search backends: DuckDuckGo, Google (CSE or library), and SerpAPI."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
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


def looks_like_product_url(url: str) -> bool:
    """Heuristic used to prefer marketplace/product URLs over category/search pages."""
    parsed = urlparse(url)
    path = parsed.path.lower()
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

    def __init__(self, api_key: str, cse_id: str, timeout: float) -> None:
        self.api_key = api_key
        self.cse_id = cse_id
        self.timeout = timeout

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": min(max_results, 10),
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

    def __init__(self, api_key: str, timeout: float, endpoint: str) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.endpoint = endpoint

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.api_key,
            "num": min(max_results, 20),
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
    if name in {"serpapi", "serp"}:
        api_key = os.getenv("SERPAPI_KEY", "").strip()
        if not api_key:
            raise RuntimeError("SEARCH_BACKEND=serpapi requires SERPAPI_KEY.")
        return SerpApiBackend(api_key, config.request_timeout, config.serpapi_url)
    if name in {"google_cse", "cse"}:
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        if not api_key or not cse_id:
            raise RuntimeError(
                "SEARCH_BACKEND=google_cse requires GOOGLE_API_KEY and GOOGLE_CSE_ID."
            )
        return GoogleCseBackend(api_key, cse_id, config.request_timeout)
    if name in {"google", "googlesearch"}:
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        if api_key and cse_id:
            logger.info("GOOGLE_API_KEY detected; using Programmable Search JSON API.")
            return GoogleCseBackend(api_key, cse_id, config.request_timeout)
        logger.warning(
            "Using googlesearch-python. Prefer SERPAPI_KEY or GOOGLE_CSE_ID for a "
            "ToS-friendly Google search."
        )
        return GoogleLibraryBackend()
    raise RuntimeError(
        f"Unknown SEARCH_BACKEND={name!r}. "
        "Use duckduckgo, google, google_cse, or serpapi."
    )


def search_web(query: str, config: AppConfig) -> list[SearchResult]:
    """Run a search and return unique, scrape-eligible results."""
    backend = build_search_backend(config)
    logger.info("Searching with backend=%s query=%r", backend.name, query)
    try:
        hits = backend.search(query, max(config.max_results * 2, config.max_pages))
    except Exception:
        logger.exception("Search backend %s failed", backend.name)
        raise

    seen: set[str] = set()
    unique: list[SearchResult] = []
    for hit in hits:
        key = hit.url.split("#", 1)[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    unique.sort(key=lambda hit: (not looks_like_product_url(hit.url), hit.url))
    logger.info("Search returned %d unique result(s)", len(unique))
    return unique[: config.max_results]
