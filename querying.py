"""Query parsing: exact tokens, model numbers like 10+, and accessory intent.

A search for “vsett 10+ scooter” must match the scooter, not a mudguard that
merely says “compatible with VSETT 10+”. Brand/model tokens are required; spare
parts are penalized unless the query itself asks for a part.

Category queries such as “best e scooter under 10k aed” are rewritten the
way a shopping search would: “e scooter” → electric scooter, “10k” → 10000,
and listings that only match the letters 10k (gold, ohms, 10KG washers) are
dropped.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from config import convert_to_base
from models import SearchResult

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "under",
        "below",
        "less",
        "than",
        "best",
        "buy",
        "cheap",
        "price",
        "review",
        "reviews",
        "online",
        "sale",
        "new",
    }
)

CURRENCY_TOKENS = frozenset(
    {"aed", "usd", "eur", "gbp", "inr", "sar", "qar", "dhs", "dh", "rs", "kwd", "bhd", "omr"}
)

_CURRENCY_ALT = r"AED|USD|EUR|GBP|INR|SAR|QAR|Dhs|DH|Rs\.?|\$|€|£|₹"

# Common product-category words. These describe what you want, but a listing
# can mention them while still being a spare part (a mudguard for a scooter).
GENERIC_TERMS = frozenset(
    {
        "scooter",
        "scooters",
        "electric",
        "bike",
        "bicycle",
        "vehicle",
        "earbuds",
        "earbud",
        "headphones",
        "headphone",
        "earphones",
        "earphone",
        "phone",
        "smartphone",
        "laptop",
        "tablet",
        "watch",
        "chair",
        "keyboard",
        "mouse",
        "monitor",
        "camera",
        "tv",
        "television",
        "wireless",
        "bluetooth",
        "pro",
        "max",
        "mini",
        "air",
        "gen",
        "generation",
    }
)

ACCESSORY_TERMS = frozenset(
    {
        "accessory",
        "accessories",
        "part",
        "parts",
        "spare",
        "spares",
        "kit",
        "kits",
        "compatible",
        "replacement",
        "mudguard",
        "mudguards",
        "fender",
        "fenders",
        "tube",
        "tubes",
        "tyre",
        "tire",
        "tyres",
        "tires",
        "damper",
        "absorber",
        "absorbers",
        "shock",
        "stabilizer",
        "stabiliser",
        "bracket",
        "mount",
        "mounting",
        "cover",
        "bag",
        "lock",
        "stand",
        "pad",
        "grip",
        "grips",
        "handlebar",
        "handlebars",
        "peca",
        "pieza",
        "bell",
        "mirror",
        "sticker",
        "decal",
        "guard",
        "protector",
        "clamp",
        "charger",  # a scooter query should not surface a charger
        "controller",
        "inner",
    }
)

ACCESSORY_NEGATIVES: tuple[str, ...] = (
    "mudguard",
    "spare",
    "kit",
    "compatible",
)

# Words that share a token with a scooter query but are a different product.
SCOOTER_OFF_CATEGORY = frozenset(
    {
        "washer",
        "washers",
        "resistor",
        "resistors",
        "ohm",
        "ohms",
        "earring",
        "earrings",
        "thermometer",
        "thermometers",
        "jewelry",
        "jewellery",
        "necklace",
        "bracelet",
        "washing",
        "10kg",
        "10kgs",
        "mobility",
    }
)

SCOOTER_SEARCH_NEGATIVES: tuple[str, ...] = (
    "resistor",
    "ohm",
    "washer",
    "earrings",
    "thermometer",
    "jewelry",
    "mobility",
)

_PLUS_MODEL = re.compile(r"\b(\d+[a-z]?)\s*(?:\+|plus)\b", re.IGNORECASE)
_E_SCOOTER = re.compile(r"\be[\s\-]?scooters?\b", re.IGNORECASE)
_E_BIKE = re.compile(r"\be[\s\-]?bikes?\b", re.IGNORECASE)
_COMPACT_K_BUDGET = re.compile(
    r"((?:under|below|less\s+than|upto|up\s+to|<)\s*)"
    rf"(?P<currency>{_CURRENCY_ALT})?"
    r"\s*"
    r"(?P<num>\d+(?:\.\d+)?)\s*[kK]\b"
    rf"(?:\s*(?P<currency2>{_CURRENCY_ALT}))?",
    re.IGNORECASE,
)
BUDGET_PATTERN = re.compile(
    r"(?:under|below|less\s+than|upto|up\s+to|<)\s*"
    rf"(?P<currency>{_CURRENCY_ALT})?\s*"
    r"(?P<amount>\d+(?:\.\d+)?\s*[kK]|\d[\d,]*(?:\.\d+)?)"
    rf"(?:\s*(?P<currency2>AED|USD|EUR|GBP|INR|SAR|QAR|Dhs|DH|Rs\.?))?",
    re.IGNORECASE,
)
_CURRENCY_ALIASES = {
    "DHS": "AED",
    "DH": "AED",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
}


def normalize_model_text(text: str) -> str:
    """Turn “10 plus” / “10+” into a stable ``10+`` token."""
    return _PLUS_MODEL.sub(r"\1+", text.lower())


def tokenize(text: str) -> list[str]:
    """Lowercase tokens, keeping model numbers such as ``10+`` intact."""
    words = re.findall(r"[a-z0-9]+(?:\+)?", normalize_model_text(text))
    return [word for word in words if word not in STOPWORDS and len(word) > 1]


def _format_budget_amount(amount: float) -> str:
    if float(amount).is_integer():
        return str(int(amount))
    return str(amount)


def _expand_compact_budget(text: str) -> str:
    """Turn “under 10k AED” into “under 10000 AED” so 10k is not a product token."""

    def repl(match: re.Match[str]) -> str:
        amount = float(match.group("num")) * 1000.0
        currency = match.group("currency") or match.group("currency2") or ""
        prefix = match.group(1)
        rendered = _format_budget_amount(amount)
        if currency:
            return f"{prefix}{rendered} {currency}"
        return f"{prefix}{rendered}"

    return _COMPACT_K_BUDGET.sub(repl, text)


def expand_shopper_query(query: str) -> str:
    """Expand shopping shorthand so search and ranking see the real product.

    “e scooter” / “e-scooter” become “electric scooter”. Compact budgets such as
    “under 10k aed” become “under 10000 aed”.
    """
    text = query.strip()
    text = _E_SCOOTER.sub("electric scooter", text)
    text = _E_BIKE.sub("electric bike", text)
    text = _expand_compact_budget(text)
    return " ".join(text.split())


def _parse_amount_token(raw: str) -> Optional[float]:
    compact = re.sub(r"\s+", "", raw.replace(",", ""))
    if not compact:
        return None
    try:
        if compact[-1] in "kK":
            return float(compact[:-1]) * 1000.0
        return float(compact)
    except ValueError:
        return None


def extract_budget(query: str) -> Optional[float]:
    """Return a numeric budget mentioned in the query, if any.

    Understands “under 200 AED” and compact forms such as “under 10k aed”
    (10000). Currency conversion of the budget itself is left to the caller.
    """
    match = BUDGET_PATTERN.search(expand_shopper_query(query))
    if not match:
        match = BUDGET_PATTERN.search(query)
    if not match:
        return None
    value = _parse_amount_token(match.group("amount"))
    if value is None or value <= 0:
        return None
    return value


def extract_budget_currency(query: str, default: str) -> str:
    for text in (expand_shopper_query(query), query):
        match = BUDGET_PATTERN.search(text)
        if not match:
            continue
        token = match.group("currency") or match.group("currency2")
        if not token:
            continue
        key = token.strip().upper()
        return _CURRENCY_ALIASES.get(key, key)
    return default


def budget_in_base(query: str, base_currency: str) -> Optional[float]:
    """Parse a query budget and convert it into ``base_currency`` using fixed FX rates."""
    amount = extract_budget(query)
    if amount is None:
        return None
    currency = extract_budget_currency(query, base_currency)
    return convert_to_base(amount, currency, base_currency)


def budget_search_clause(query: str) -> str:
    """Natural-language budget for the web query, e.g. “under 10000 AED”."""
    amount = extract_budget(query)
    if amount is None:
        return ""
    currency = extract_budget_currency(query, "")
    rendered = _format_budget_amount(amount)
    if currency:
        return f"under {rendered} {currency}"
    return f"under {rendered}"


def _budget_tokens_to_drop(query: str) -> set[str]:
    drop: set[str] = set(CURRENCY_TOKENS)
    for text in (query, expand_shopper_query(query)):
        match = BUDGET_PATTERN.search(text)
        if not match:
            continue
        raw = match.group("amount").replace(",", "").replace(" ", "").lower()
        drop.add(raw)
        value = _parse_amount_token(match.group("amount"))
        if value is not None and float(value).is_integer():
            drop.add(str(int(value)))
        if raw.endswith("k"):
            drop.add(raw)
    return drop


def query_match_terms(query: str) -> list[str]:
    """Query tokens used for matching, minus budget amounts and currency codes."""
    expanded = expand_shopper_query(query)
    terms = tokenize(expanded)
    drop = _budget_tokens_to_drop(query)
    return [term for term in terms if term not in drop]


def required_terms(query: str) -> list[str]:
    """Brand / model tokens that must appear on a true match (e.g. vsett, 10+)."""
    return [term for term in query_match_terms(query) if term not in GENERIC_TERMS]


def query_wants_parts(query: str) -> bool:
    """True when the shopper is explicitly looking for a spare or accessory."""
    return any(term in ACCESSORY_TERMS for term in tokenize(expand_shopper_query(query)))


def wants_electric_scooter(query: str) -> bool:
    """True for “e scooter”, “e-scooter”, or “electric scooter” shopping queries."""
    lowered = query.lower()
    if _E_SCOOTER.search(lowered):
        return True
    tokens = set(tokenize(expand_shopper_query(query)))
    return "electric" in tokens and "scooter" in tokens


def looks_like_electric_scooter(text: str) -> bool:
    """True when the listing is an electric scooter, not a motorcycle part."""
    lowered = text.lower().replace("-", " ")
    if "electric scooter" in lowered:
        return True
    if re.search(r"\bescooters?\b", lowered) or re.search(r"\be scooters?\b", lowered):
        return True
    tokens = set(tokenize(text))
    return "electric" in tokens and "scooter" in tokens


def is_off_category(query: str, text: str) -> bool:
    """True when the listing is a different product that collides on a token."""
    q_tokens = set(query_match_terms(query))
    if "scooter" not in q_tokens and "scooters" not in q_tokens:
        return False
    tokens = set(tokenize(text))
    if tokens & SCOOTER_OFF_CATEGORY:
        return True
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in ("washing machine", "10k ohm", "10k gold", "10kt ", "10k yellow")
    )


def category_matches(query: str, text: str) -> bool:
    """True when the listing is the kind of product the query asked for."""
    if is_off_category(query, text):
        return False
    if wants_electric_scooter(query):
        return looks_like_electric_scooter(text)
    return True


def _term_in_text(term: str, tokens: set[str], text: str) -> bool:
    """Match ``10+`` to ``10+`` or a bare ``10`` that is not a tyre size like 10x3."""
    if term in tokens:
        return True
    if term.endswith("+"):
        base = term[:-1]
        if not base or base not in tokens:
            return False
        lowered = text.lower()
        if re.search(rf"\b{re.escape(base)}x", lowered):
            return False
        if re.search(rf"\b{re.escape(base)}\s*-?\s*inch", lowered) and f"{base}+" not in lowered:
            # “10 inch tube” is a size, not the 10+ model — unless 10+ is also present.
            return False
        return True
    return False


def missing_required(query: str, text: str) -> list[str]:
    tokens = set(tokenize(text))
    return [term for term in required_terms(query) if not _term_in_text(term, tokens, text)]


_MODELISH = re.compile(r"^(?:[a-z]{0,5}\d+[a-z]{0,4}|\d+[a-z]?)$", re.I)


def is_modelish_term(term: str) -> bool:
    """True for model codes such as ``gt3``, ``10+``, or ``s2`` — not brand names."""
    if term.endswith("+"):
        return True
    return bool(_MODELISH.fullmatch(term))


def missing_hard_required(query: str, text: str) -> list[str]:
    """Brand words that must appear; model codes may be missing from a URL slug."""
    return [term for term in missing_required(query, text) if not is_modelish_term(term)]


def prefer_query_aware_title(query: str, extracted: str, fallback: str) -> str:
    """Keep the search title when the scraped heading dropped the model name."""
    extracted = clean_listing_title(query, extracted)
    fallback = clean_listing_title(query, fallback)
    if not fallback:
        return extracted
    if not extracted:
        return fallback
    extracted_missing = missing_required(query, extracted)
    fallback_missing = missing_required(query, fallback)
    if extracted_missing and len(fallback_missing) < len(extracted_missing):
        return fallback
    if not fallback_missing and category_matches(query, fallback) and not category_matches(
        query, extracted
    ):
        # Amazon often returns a short og:title (“NAVEE GT3”) without “scooter”.
        return fallback
    if extracted_missing:
        return extracted
    return extracted


def clean_listing_title(query: str, title: str) -> str:
    """Take the first product name when a search hit concatenates several titles."""
    text = re.sub(r"\s+", " ", (title or "")).strip(" .")
    if not text:
        return ""
    parts = [part.strip(" .") for part in re.split(r"\s*\.{2,}\s*", text) if part.strip(" .")]
    if len(parts) <= 1 and " | " not in text:
        return text[:180].rstrip()
    candidates = parts if len(parts) > 1 else [p.strip() for p in text.split(" | ") if p.strip()]
    req = required_terms(query)
    for part in candidates:
        if req and missing_hard_required(query, part):
            continue
        if looks_like_electric_scooter(part) or not req:
            return part[:160].rstrip()
    return (candidates[0] if candidates else text)[:160].rstrip()


def accessory_multiplier(query: str, title: str) -> float:
    """1.0 for a complete product; a small factor when the title is a spare part."""
    if query_wants_parts(query):
        return 1.0
    title_l = title.lower()
    title_tokens = set(tokenize(title))
    if "compatible with" in title_l or "compatible" in title_tokens:
        return 0.12
    if title_tokens & ACCESSORY_TERMS:
        return 0.14
    brands = required_terms(query)
    if brands:
        brand = re.escape(brands[0])
        if re.search(rf"\b(?:for|para|für|pour)\s+{brand}\b", title_l) and not title_l.strip().startswith(
            brands[0]
        ):
            return 0.14
    return 1.0


def _vehicle_query(query: str) -> bool:
    terms = set(query_match_terms(query))
    return bool(terms & {"scooter", "scooters", "bike", "bicycle", "vehicle"})


def category_search_negatives(query: str) -> tuple[str, ...]:
    if "scooter" in query_match_terms(query) or wants_electric_scooter(query):
        return SCOOTER_SEARCH_NEGATIVES
    return ()


def shopping_followup_queries(query: str, country_term: str) -> list[str]:
    """Named-product searches so ranking sees listings, not category indexes."""
    from intent import catalog_search_queries

    return catalog_search_queries(query, country_term)


def product_core_query(query: str) -> str:
    """Brand and product words only — used with site:amazon.ae so negatives do not hide listings."""
    required = required_terms(query)
    generic = [term for term in query_match_terms(query) if term in GENERIC_TERMS][:3]
    if required:
        core = f'"{" ".join(required)}"'
        if generic:
            core = f"{core} {' '.join(generic)}"
        return core
    return " ".join(query_match_terms(query)) or expand_shopper_query(query)


def precise_search_query(query: str) -> str:
    """Rewrite the web query like a shopping search, not a token dump.

    Brand searches stay quoted (“vsett 10+”). Category queries become
    ``"electric scooter" under 10000 AED`` instead of matching the letters 10k.
    """
    required = required_terms(query)
    generic = [term for term in query_match_terms(query) if term in GENERIC_TERMS]
    if required:
        quoted = " ".join(required)
        core = f'"{quoted}"'
        if generic:
            core = f"{core} {' '.join(generic)}"
    elif generic:
        core = f'"{" ".join(generic)}"'
    else:
        core = " ".join(query_match_terms(query)) or expand_shopper_query(query)

    budget_clause = budget_search_clause(query)
    if budget_clause and budget_clause.lower() not in core.lower():
        core = f"{core} {budget_clause}"

    negatives: list[str] = []
    if not query_wants_parts(query):
        if required or _vehicle_query(query):
            negatives.extend(ACCESSORY_NEGATIVES)
        negatives.extend(category_search_negatives(query))
    if negatives:
        seen: set[str] = set()
        unique: list[str] = []
        for word in negatives:
            if word not in seen:
                seen.add(word)
                unique.append(word)
        core = f"{core} " + " ".join(f"-{word}" for word in unique)
    return core


def hit_is_plausible(query: str, title: str, snippet: str = "", url: str = "") -> bool:
    """Cheap pre-scrape check: brand present and not an obvious spare part.

    Model codes (``10+``, ``gt3``) are optional here so marketplace pages whose
    URL slug is “NAVEE Electric Scooter” are not dropped before we can rank them.
    """
    slug = url.replace("-", " ").replace("/", " ").replace("_", " ")
    # Site-restricted search snippets often echo the query onto unrelated listings.
    # Require the brand in the title or URL, not only in the snippet.
    title_url = f"{title} {slug}"
    if missing_hard_required(query, title_url):
        return False
    blob = f"{title} {snippet} {slug}"
    if accessory_multiplier(query, f"{title} {slug}") < 0.5:
        return False
    if not category_matches(query, blob):
        return False
    lowered = f"{title} {snippet}".lower()
    if not query_wants_parts(query) and any(
        marker in lowered
        for marker in (
            "wiki",
            "guía",
            "guia completa",
            "buying guide",
            "how to choose",
            "pros and cons",
            "need suggestion",
        )
    ):
        return False
    return True


def sort_hits_for_query(query: str, hits: Iterable[SearchResult]) -> list[SearchResult]:
    """Prefer on-query product hits so scrape budget is not spent on parts."""
    ranked: list[SearchResult] = []
    for hit in hits:
        plausible = hit_is_plausible(query, hit.title, hit.snippet)
        accessory = accessory_multiplier(query, hit.title) < 0.5
        ranked.append((not plausible, accessory, hit))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [hit for _, __, hit in ranked]
