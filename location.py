"""Country profiles, listing availability, and location-aware search queries.

FindBest prefers items you can actually buy: stores in your current country,
plus cross-border sellers that ship there (AliExpress, Temu, and similar).
Listings that belong to another country's storefront are kept only as a
fallback when there are not enough local or deliverable results.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse

from config import AppConfig


AvailabilityKind = str  # "local" | "ships" | "unknown" | "foreign"


@dataclass(frozen=True)
class CountryProfile:
    """Where the shopper is, and which stores count as buyable from there."""

    code: str
    name: str
    currency: str
    search_region: str
    google_gl: str
    location_name: str
    search_terms: tuple[str, ...]
    query_tokens: tuple[str, ...]
    local_domains: tuple[str, ...]
    local_tlds: tuple[str, ...] = ()
    path_hints: tuple[str, ...] = ()
    extra_ships_domains: tuple[str, ...] = ()
    example_queries: tuple[str, ...] = ()
    google_hl: str = "en"


@dataclass(frozen=True)
class ListingAvailability:
    """How buyable a URL is from the shopper's country."""

    kind: AvailabilityKind
    score: float
    label: str


# Cross-border marketplaces that routinely ship internationally.
GLOBAL_SHIPS_DOMAINS: tuple[str, ...] = (
    "aliexpress.com",
    "aliexpress.us",
    "aliexpress.ru",
    "temu.com",
    "shein.com",
    "dhgate.com",
    "banggood.com",
    "lightinthebox.com",
    "geekbuying.com",
    "wish.com",
    "joom.com",
)

# Domain suffix → the country that storefront is built for.
MARKETPLACE_HOME: dict[str, str] = {
    "amazon.ae": "AE",
    "amazon.sa": "SA",
    "amazon.eg": "EG",
    "amazon.in": "IN",
    "amazon.com": "US",
    "amazon.co.uk": "GB",
    "amazon.de": "DE",
    "amazon.ca": "CA",
    "amazon.com.au": "AU",
    "amazon.fr": "FR",
    "amazon.it": "IT",
    "amazon.es": "ES",
    "amazon.co.jp": "JP",
    "amazon.sg": "SG",
    "flipkart.com": "IN",
    "myntra.com": "IN",
    "ajio.com": "IN",
    "snapdeal.com": "IN",
    "meesho.com": "IN",
    "croma.com": "IN",
    "reliancedigital.in": "IN",
    "tatacliq.com": "IN",
    "nykaa.com": "IN",
    "walmart.com": "US",
    "target.com": "US",
    "bestbuy.com": "US",
    "homedepot.com": "US",
    "lowes.com": "US",
    "costco.com": "US",
    "ebay.com": "US",
    "argos.co.uk": "GB",
    "johnlewis.com": "GB",
    "currys.co.uk": "GB",
    "tesco.com": "GB",
    "ebay.co.uk": "GB",
    "jarir.com": "SA",
    "extra.com": "SA",
    "noon.com": "AE",
    "naveetech.com": "US",
    "naveetech.us": "US",
    "wellbots.com": "US",
}

# Public suffixes that name a country. Generic .com is not a country.
COUNTRY_TLDS: tuple[tuple[str, str], ...] = (
    (".co.uk", "GB"),
    (".com.au", "AU"),
    (".co.in", "IN"),
    (".co.jp", "JP"),
    (".com.sa", "SA"),
    (".ae", "AE"),
    (".us", "US"),
    (".uk", "GB"),
    (".in", "IN"),
    (".de", "DE"),
    (".fr", "FR"),
    (".ca", "CA"),
    (".au", "AU"),
    (".sa", "SA"),
    (".eg", "EG"),
    (".pk", "PK"),
    (".qa", "QA"),
    (".kw", "KW"),
    (".bh", "BH"),
    (".om", "OM"),
)

# Sites that serve several countries from one domain; path decides locality.
PATH_COUNTRY_SITES: dict[str, tuple[tuple[str, str], ...]] = {
    "noon.com": (("/uae", "AE"), ("/saudi", "SA"), ("/egypt", "EG"), ("/bahrain", "BH")),
    "ikea.com": (("/ae/", "AE"), ("/in/", "IN"), ("/us/", "US"), ("/gb/", "GB"), ("/sa/", "SA")),
    "apple.com": (("/ae/", "AE"), ("/in/", "IN"), ("/sa/", "SA"), ("/uk/", "GB")),
    "samsung.com": (("/ae/", "AE"), ("/in/", "IN"), ("/uk/", "GB")),
}

# Leading subdomain that names a country storefront (saudi.sharafdg.com, uae.example.com).
SUBDOMAIN_COUNTRY: dict[str, str] = {
    "ae": "AE",
    "uae": "AE",
    "dubai": "AE",
    "sa": "SA",
    "ksa": "SA",
    "saudi": "SA",
    "qa": "QA",
    "qatar": "QA",
    "kw": "KW",
    "kuwait": "KW",
    "bh": "BH",
    "bahrain": "BH",
    "om": "OM",
    "oman": "OM",
    "eg": "EG",
    "egypt": "EG",
    "in": "IN",
    "india": "IN",
    "pk": "PK",
    "uk": "GB",
    "gb": "GB",
    "us": "US",
    "ca": "CA",
    "au": "AU",
    "de": "DE",
}
REGIONAL_LOCAL: dict[str, frozenset[str]] = {
    "noon.com": frozenset({"AE", "SA", "EG", "BH"}),
    "namshi.com": frozenset({"AE", "SA", "KW", "OM", "BH", "QA"}),
    "mumzworld.com": frozenset({"AE", "SA", "KW", "OM", "BH", "QA"}),
    "ebay.com": frozenset({"US", "CA", "GB", "AU"}),
}

AVAILABILITY_SCORES: dict[str, float] = {
    "local": 1.0,
    "ships": 0.78,
    "unknown": 0.42,
    "foreign": 0.12,
}


def _ae() -> CountryProfile:
    return CountryProfile(
        code="AE",
        name="United Arab Emirates",
        currency="AED",
        search_region="ae-en",
        google_gl="ae",
        location_name="United Arab Emirates",
        search_terms=("UAE", "Dubai"),
        query_tokens=("aed", "dhs", "dubai", "uae", "emirates"),
        local_domains=(
            "amazon.ae",
            "noon.com",
            "sharafdg.com",
            "jumbo.ae",
            "luluhypermarket.com",
            "carrefouruae.com",
            "virginmegastore.ae",
            "namshi.com",
            "ounass.com",
            "mumzworld.com",
            "emaxme.com",
            "jackys.com",
            "dubizzle.com",
            "homecentre.com",
            "drhead.ae",
            "ecityuae.ae",
            "gadgetsworld.ae",
            "gear-up.me",
            "awok.com",
            "servicecentre.ae",
            "unioncoop.ae",
            "kmart.ae",
            "maxfashion.com",
            "mi.com",
            "buytronics.ae",
            "dubaiscooters.ae",
            "whizz.ae",
            "naveetech.ae",
        ),
        local_tlds=(".ae",),
        path_hints=("/uae", "/ae/", "/en-ae", "/en_ae"),
        example_queries=(
            "best e scooter under 10k aed",
            "wireless earbuds under 200 AED",
            "noise cancelling headphones",
        ),
    )


def _in() -> CountryProfile:
    return CountryProfile(
        code="IN",
        name="India",
        currency="INR",
        search_region="in-en",
        google_gl="in",
        location_name="India",
        search_terms=("India",),
        query_tokens=("inr", "rupee", "rupees", "india", "flipkart"),
        local_domains=(
            "amazon.in",
            "flipkart.com",
            "myntra.com",
            "ajio.com",
            "snapdeal.com",
            "croma.com",
            "reliancedigital.in",
            "tatacliq.com",
            "nykaa.com",
            "meesho.com",
            "jiomart.com",
            "vijaysales.com",
            "shopclues.com",
        ),
        local_tlds=(".in",),
        path_hints=("/in/", "/en-in"),
        example_queries=(
            "wireless earbuds under 2000 INR",
            "noise cancelling headphones",
            "office chair under 8000 INR",
        ),
    )


def _sa() -> CountryProfile:
    return CountryProfile(
        code="SA",
        name="Saudi Arabia",
        currency="SAR",
        search_region="sa-en",
        google_gl="sa",
        location_name="Saudi Arabia",
        search_terms=("Saudi", "KSA"),
        query_tokens=("sar", "riyadh", "jeddah", "ksa", "saudi"),
        local_domains=(
            "amazon.sa",
            "noon.com",
            "jarir.com",
            "extra.com",
            "namshi.com",
            "luluhypermarket.com",
        ),
        local_tlds=(".sa",),
        path_hints=("/sa/", "/saudi", "/en-sa"),
        example_queries=(
            "wireless earbuds under 200 SAR",
            "noise cancelling headphones",
        ),
    )


COUNTRY_PROFILES: dict[str, CountryProfile] = {
    "AE": _ae(),
    "IN": _in(),
    "SA": _sa(),
    "US": CountryProfile(
        code="US",
        name="United States",
        currency="USD",
        search_region="us-en",
        google_gl="us",
        location_name="United States",
        search_terms=("USA",),
        query_tokens=("usd", "usa", "united states"),
        local_domains=("amazon.com", "walmart.com", "target.com", "bestbuy.com", "ebay.com", "costco.com"),
        local_tlds=(".us",),
        path_hints=("/us/",),
        example_queries=("wireless earbuds under $40", "noise cancelling headphones"),
    ),
    "GB": CountryProfile(
        code="GB",
        name="United Kingdom",
        currency="GBP",
        search_region="uk-en",
        google_gl="uk",
        location_name="United Kingdom",
        search_terms=("UK",),
        query_tokens=("gbp", "uk", "britain", "united kingdom"),
        local_domains=("amazon.co.uk", "argos.co.uk", "johnlewis.com", "currys.co.uk", "ebay.co.uk"),
        local_tlds=(".uk",),
        path_hints=("/uk/", "/en-gb"),
        example_queries=("wireless earbuds under £40", "noise cancelling headphones"),
    ),
    "QA": CountryProfile(
        code="QA",
        name="Qatar",
        currency="QAR",
        search_region="qa-en",
        google_gl="qa",
        location_name="Qatar",
        search_terms=("Qatar", "Doha"),
        query_tokens=("qar", "qatar", "doha"),
        local_domains=("luluhypermarket.com", "virginmegastore.qa", "lulu.qa"),
        local_tlds=(".qa",),
        path_hints=("/qa/", "/qatar"),
        extra_ships_domains=("amazon.ae", "noon.com"),
        example_queries=("wireless earbuds under 200 QAR",),
    ),
    "KW": CountryProfile(
        code="KW",
        name="Kuwait",
        currency="KWD",
        search_region="kw-en",
        google_gl="kw",
        location_name="Kuwait",
        search_terms=("Kuwait",),
        query_tokens=("kwd", "kuwait"),
        local_domains=("xcite.com", "luluhypermarket.com"),
        local_tlds=(".kw",),
        extra_ships_domains=("amazon.ae", "noon.com"),
        example_queries=("wireless earbuds",),
    ),
    "BH": CountryProfile(
        code="BH",
        name="Bahrain",
        currency="BHD",
        search_region="bh-en",
        google_gl="bh",
        location_name="Bahrain",
        search_terms=("Bahrain",),
        query_tokens=("bhd", "bahrain"),
        local_domains=("luluhypermarket.com", "sharafdg.com"),
        local_tlds=(".bh",),
        extra_ships_domains=("amazon.ae", "noon.com"),
        example_queries=("wireless earbuds",),
    ),
    "OM": CountryProfile(
        code="OM",
        name="Oman",
        currency="OMR",
        search_region="om-en",
        google_gl="om",
        location_name="Oman",
        search_terms=("Oman", "Muscat"),
        query_tokens=("omr", "oman", "muscat"),
        local_domains=("sharafdg.com", "luluhypermarket.com"),
        local_tlds=(".om",),
        extra_ships_domains=("amazon.ae", "noon.com"),
        example_queries=("wireless earbuds",),
    ),
    "EG": CountryProfile(
        code="EG",
        name="Egypt",
        currency="EGP",
        search_region="eg-en",
        google_gl="eg",
        location_name="Egypt",
        search_terms=("Egypt", "Cairo"),
        query_tokens=("egp", "egypt", "cairo"),
        local_domains=("amazon.eg", "noon.com", "jumia.com"),
        local_tlds=(".eg",),
        path_hints=("/egypt", "/eg/"),
        example_queries=("wireless earbuds",),
    ),
    "PK": CountryProfile(
        code="PK",
        name="Pakistan",
        currency="PKR",
        search_region="pk-en",
        google_gl="pk",
        location_name="Pakistan",
        search_terms=("Pakistan",),
        query_tokens=("pkr", "pakistan"),
        local_domains=("daraz.pk", "goto.com.pk"),
        local_tlds=(".pk",),
        extra_ships_domains=("aliexpress.com",),
        example_queries=("wireless earbuds under 5000 PKR",),
    ),
    "CA": CountryProfile(
        code="CA",
        name="Canada",
        currency="CAD",
        search_region="ca-en",
        google_gl="ca",
        location_name="Canada",
        search_terms=("Canada",),
        query_tokens=("cad", "canada"),
        local_domains=("amazon.ca", "walmart.ca", "bestbuy.ca", "canadiantire.ca"),
        local_tlds=(".ca",),
        example_queries=("wireless earbuds under $80",),
    ),
    "AU": CountryProfile(
        code="AU",
        name="Australia",
        currency="AUD",
        search_region="au-en",
        google_gl="au",
        location_name="Australia",
        search_terms=("Australia",),
        query_tokens=("aud", "australia"),
        local_domains=("amazon.com.au", "ebay.com.au", "jbhifi.com.au", "kogan.com"),
        local_tlds=(".au",),
        example_queries=("wireless earbuds under $80",),
    ),
    "DE": CountryProfile(
        code="DE",
        name="Germany",
        currency="EUR",
        search_region="de-en",
        google_gl="de",
        location_name="Germany",
        search_terms=("Germany",),
        query_tokens=("eur", "germany", "deutschland"),
        local_domains=("amazon.de", "otto.de", "mediamarkt.de"),
        local_tlds=(".de",),
        example_queries=("wireless earbuds under 80 EUR",),
    ),
}

_QUERY_COUNTRY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b({ '|'.join(re.escape(tok) for tok in profile.query_tokens) })\b", re.I), code)
    for code, profile in COUNTRY_PROFILES.items()
    if profile.query_tokens
)

# Currency / symbol hints that are not already covered as query tokens.
_EXTRA_QUERY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bAED\b|د\.إ"), "AE"),
    (re.compile(r"\bINR\b|₹"), "IN"),
    (re.compile(r"\bSAR\b"), "SA"),
    (re.compile(r"\bGBP\b|£"), "GB"),
    (re.compile(r"\bUSD\b|(?<!\S)\$(?!\s*AUD)"), "US"),
    (re.compile(r"\bEUR\b|€"), "DE"),
)


def list_countries() -> list[CountryProfile]:
    """Stable dropdown order: Gulf, then India, then other common destinations."""
    order = ("AE", "SA", "QA", "KW", "BH", "OM", "EG", "IN", "PK", "US", "GB", "DE", "CA", "AU")
    return [COUNTRY_PROFILES[code] for code in order if code in COUNTRY_PROFILES]


def get_country(code: str | None) -> CountryProfile:
    """Return a known profile, defaulting to the UAE (the app's original market)."""
    key = (code or "").strip().upper()
    if key == "UK":
        key = "GB"
    if key == "UAE":
        key = "AE"
    return COUNTRY_PROFILES.get(key, COUNTRY_PROFILES["AE"])


def country_from_query(query: str) -> Optional[str]:
    """Infer a country code from currency or place words in the query."""
    text = query.strip()
    if not text:
        return None
    for pattern, code in _QUERY_COUNTRY_PATTERNS:
        if pattern.search(text):
            return code
    for pattern, code in _EXTRA_QUERY_HINTS:
        if pattern.search(text):
            return code
    return None


# IANA time zone → shopper country (the system clock, no permission prompt).
TZ_COUNTRY: dict[str, str] = {
    "Asia/Dubai": "AE",
    "Asia/Muscat": "OM",
    "Asia/Riyadh": "SA",
    "Asia/Qatar": "QA",
    "Asia/Kuwait": "KW",
    "Asia/Bahrain": "BH",
    "Africa/Cairo": "EG",
    "Asia/Kolkata": "IN",
    "Asia/Calcutta": "IN",
    "Asia/Karachi": "PK",
    "America/New_York": "US",
    "America/Chicago": "US",
    "America/Denver": "US",
    "America/Los_Angeles": "US",
    "America/Phoenix": "US",
    "America/Anchorage": "US",
    "America/Detroit": "US",
    "America/Boise": "US",
    "America/Indiana/Indianapolis": "US",
    "Pacific/Honolulu": "US",
    "America/Toronto": "CA",
    "America/Vancouver": "CA",
    "America/Winnipeg": "CA",
    "America/Edmonton": "CA",
    "America/Halifax": "CA",
    "America/Montreal": "CA",
    "Europe/London": "GB",
    "Europe/Belfast": "GB",
    "Europe/Berlin": "DE",
    "Australia/Sydney": "AU",
    "Australia/Melbourne": "AU",
    "Australia/Perth": "AU",
    "Australia/Brisbane": "AU",
    "Australia/Adelaide": "AU",
}

_CANADA_TZ_CITIES = frozenset(
    {"Toronto", "Vancouver", "Winnipeg", "Edmonton", "Halifax", "Montreal", "Calgary"}
)


def country_from_timezone(name: str | None) -> Optional[str]:
    """Map the device IANA time zone to a country we shop for."""
    if not name:
        return None
    key = name.strip()
    if not key or key.upper() in {"UTC", "GMT", "ETC/UTC"}:
        return None
    mapped = TZ_COUNTRY.get(key)
    if mapped:
        return mapped
    if key.startswith("America/"):
        city = key.rsplit("/", 1)[-1]
        if city in _CANADA_TZ_CITIES:
            return "CA"
        if any(part in key for part in ("Mexico", "Argentina", "Sao_Paulo", "Lima", "Bogota", "Santiago")):
            return None
        return "US"
    if key.startswith("Australia/"):
        return "AU"
    return None


def country_from_locale(locale: str | None) -> Optional[str]:
    """Map a BCP 47 locale such as ``en-IN`` to a country code."""
    if not locale:
        return None
    match = re.search(r"^[a-z]{2}[-_]([a-z]{2})", locale.strip(), re.I)
    if not match:
        return None
    region = match.group(1).upper()
    if region in COUNTRY_PROFILES or region in {"UK", "UAE"}:
        return get_country(region).code
    return None


def country_from_system() -> Optional[str]:
    """Read the operating system's current time zone."""
    try:
        from datetime import datetime

        tzinfo = datetime.now().astimezone().tzinfo
        key = getattr(tzinfo, "key", None)
        found = country_from_timezone(key)
        if found:
            return found
    except Exception:  # noqa: BLE001
        pass
    return country_from_timezone(os.environ.get("TZ"))


def country_from_headers(headers: dict[str, str] | None) -> Optional[str]:
    """Read a country code from common CDN / proxy geo headers."""
    if not headers:
        return None
    lowered = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    for header in (
        "cf-ipcountry",
        "x-appengine-country",
        "cloudfront-viewer-country",
        "x-country-code",
        "x-geo-country",
    ):
        value = lowered.get(header, "").upper()
        if value and value not in {"XX", "T1", "ZZ", ""}:
            if value in COUNTRY_PROFILES or value in {"UK", "UAE"}:
                return get_country(value).code
    language = lowered.get("accept-language", "")
    match = re.search(r"^[a-z]{2}[-_]([a-z]{2})", language, re.I)
    if match:
        region = match.group(1).upper()
        if region in COUNTRY_PROFILES or region in {"UK", "UAE"}:
            return get_country(region).code
    return None


def apply_country(config: AppConfig, code: str, *, set_currency: bool = False) -> CountryProfile:
    """Copy location fields from ``code`` onto ``config``."""
    profile = get_country(code)
    config.country_code = profile.code
    config.search_region = profile.search_region
    config.google_gl = profile.google_gl
    config.google_hl = profile.google_hl
    config.google_location = profile.location_name
    if set_currency:
        config.base_currency = profile.currency
    return profile


def resolve_country(
    config: AppConfig,
    query: str = "",
    explicit: str | None = None,
    headers: dict[str, str] | None = None,
    timezone: str | None = None,
    locale: str | None = None,
) -> CountryProfile:
    """Pick a country from the query market first, then this device.

    The shopper is not asked to choose a location. An explicit currency or
    place in the query (AED, India, “in Dubai”) selects that market — the same
    way searching “under 10k aed” should shop the UAE from any device. When the
    query has no place signal, the device time zone wins.
    """
    if explicit:
        return apply_country(config, explicit)
    hinted = country_from_query(query)
    if hinted:
        return apply_country(config, hinted)
    from_tz = country_from_timezone(timezone)
    if from_tz:
        return apply_country(config, from_tz)
    geo = country_from_headers(headers)
    if geo:
        return apply_country(config, geo)
    from_locale = country_from_locale(locale)
    if from_locale:
        return apply_country(config, from_locale)
    env_code = os.getenv("PRODUCT_FINDER_COUNTRY", "").strip()
    if env_code:
        return apply_country(config, env_code)
    return apply_country(config, config.country_code or "AE")


def _host(url_or_host: str) -> str:
    if "://" in url_or_host:
        host = urlparse(url_or_host).netloc.lower()
    else:
        host = url_or_host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _host_matches(host: str, domains: Iterable[str]) -> bool:
    for domain in domains:
        domain = domain.lower().strip()
        if not domain:
            continue
        if host == domain or host.endswith("." + domain):
            return True
    return False


def _marketplace_home(host: str) -> Optional[str]:
    matches = [domain for domain in MARKETPLACE_HOME if host == domain or host.endswith("." + domain)]
    if not matches:
        return None
    longest = max(matches, key=len)
    return MARKETPLACE_HOME[longest]


def _path_country(host: str, path: str) -> Optional[str]:
    rules = PATH_COUNTRY_SITES.get(host)
    if not rules:
        for site, site_rules in PATH_COUNTRY_SITES.items():
            if host == site or host.endswith("." + site):
                rules = site_rules
                break
    if not rules:
        return None
    path_l = path.lower()
    for hint, code in rules:
        if hint in path_l:
            return code
    return None


def _kind_label(kind: AvailabilityKind, country: CountryProfile) -> str:
    if kind == "local":
        return f"Sold in {country.name}"
    if kind == "ships":
        return f"Ships to {country.name}"
    if kind == "foreign":
        return f"Other country — may not ship to {country.name}"
    return "Availability unclear"


def _tld_country(host: str) -> Optional[str]:
    """Return a country code when the domain uses a country public suffix (.ae, .us)."""
    for suffix, code in COUNTRY_TLDS:
        if host.endswith(suffix):
            return code
    return None


def _subdomain_country(host: str) -> Optional[str]:
    """Return a country code when the leftmost label is a country storefront."""
    first = host.split(".")[0]
    return SUBDOMAIN_COUNTRY.get(first)


def classify_listing(url: str, source_domain: str, country: CountryProfile) -> ListingAvailability:
    """Classify a product URL as local, ships-here, foreign, or unknown."""
    host = _host(source_domain or url)
    path = urlparse(url).path.lower() if "://" in url else ""
    url_l = url.lower()

    path_code = _path_country(host, path or url_l)
    sub_code = _subdomain_country(host)
    if path_code == country.code or sub_code == country.code:
        kind: AvailabilityKind = "local"
    elif (path_code and path_code != country.code) or (sub_code and sub_code != country.code):
        kind = "foreign"
    elif _host_matches(host, country.local_domains) or any(host.endswith(tld) for tld in country.local_tlds):
        kind = "local"
    elif any(hint in url_l for hint in country.path_hints):
        kind = "local"
    elif _host_matches(host, GLOBAL_SHIPS_DOMAINS) or _host_matches(host, country.extra_ships_domains):
        kind = "ships"
    else:
        home = _marketplace_home(host)
        regional = None
        for site, codes in REGIONAL_LOCAL.items():
            if host == site or host.endswith("." + site):
                regional = codes
                break
        if regional and country.code in regional:
            kind = "local"
        elif home == country.code:
            kind = "local"
        elif home and home != country.code:
            kind = "foreign"
        else:
            tld_code = _tld_country(host)
            if tld_code == country.code:
                kind = "local"
            elif tld_code and tld_code != country.code:
                kind = "foreign"
            else:
                kind = "unknown"

    return ListingAvailability(
        kind=kind,
        score=AVAILABILITY_SCORES[kind],
        label=_kind_label(kind, country),
    )


def is_buyable(kind: AvailabilityKind) -> bool:
    return kind in {"local", "ships"}


def localize_query(query: str, country: CountryProfile) -> str:
    """Append a country term so web indexes prefer local listings."""
    text = query.lower()
    if any(token in text for token in country.query_tokens):
        return query
    if any(term.lower() in text for term in country.search_terms):
        return query
    if country.code.lower() in text.split():
        return query
    return f"{query} {country.search_terms[0]}"


def marketplace_site_queries(query: str, country: CountryProfile) -> list[str]:
    """One search per local store so amazon.ae is not lost in a giant OR-query."""
    queries = [f"{query} site:{domain}" for domain in country.local_domains[:3]]
    ships = country.extra_ships_domains[:1] or ("aliexpress.com",)
    queries.append(f"{query} site:{ships[0]}")
    return queries
