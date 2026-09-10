"""Query parsing: exact tokens, model numbers like 10+, and accessory intent.

A search for “vsett 10+ scooter” must match the scooter, not a mudguard that
merely says “compatible with VSETT 10+”. Brand/model tokens are required; spare
parts are penalized unless the query itself asks for a part.
"""

from __future__ import annotations

import re
from typing import Iterable

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
        "bell",
        "mirror",
        "sticker",
        "decal",
        "guard",
        "protector",
        "clamp",
        "charger",  # a scooter query should not surface a charger
        "inner",
    }
)

ACCESSORY_NEGATIVES: tuple[str, ...] = (
    "mudguard",
    "spare",
    "kit",
    "compatible",
)

_PLUS_MODEL = re.compile(r"\b(\d+[a-z]?)\s*(?:\+|plus)\b", re.IGNORECASE)


def normalize_model_text(text: str) -> str:
    """Turn “10 plus” / “10+” into a stable ``10+`` token."""
    return _PLUS_MODEL.sub(r"\1+", text.lower())


def tokenize(text: str) -> list[str]:
    """Lowercase tokens, keeping model numbers such as ``10+`` intact."""
    words = re.findall(r"[a-z0-9]+(?:\+)?", normalize_model_text(text))
    return [word for word in words if word not in STOPWORDS and len(word) > 1]


_BUDGET_AMOUNT = re.compile(
    r"(?:under|below|less\s+than|upto|up\s+to|<)\s*"
    r"(?:AED|USD|EUR|GBP|INR|SAR|QAR|Dhs|DH|Rs\.?|\$|€|£|₹)?\s*"
    r"(\d[\d,]*)",
    re.IGNORECASE,
)


def query_match_terms(query: str) -> list[str]:
    """Query tokens used for matching, minus budget amounts and currency codes."""
    terms = tokenize(query)
    drop: set[str] = set(CURRENCY_TOKENS)
    match = _BUDGET_AMOUNT.search(query)
    if match:
        raw = match.group(1).replace(",", "")
        drop.add(raw)
        if raw.isdigit():
            drop.add(str(int(raw)))
    return [term for term in terms if term not in drop]


def required_terms(query: str) -> list[str]:
    """Brand / model tokens that must appear on a true match (e.g. vsett, 10+)."""
    return [term for term in query_match_terms(query) if term not in GENERIC_TERMS]


def query_wants_parts(query: str) -> bool:
    """True when the shopper is explicitly looking for a spare or accessory."""
    return any(term in ACCESSORY_TERMS for term in tokenize(query))


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
        if re.search(rf"\bfor\s+{brand}\b", title_l) and not title_l.strip().startswith(brands[0]):
            return 0.14
    return 1.0


def precise_search_query(query: str) -> str:
    """Rewrite the web query: quote brand+model, drop spare-part listings."""
    required = required_terms(query)
    generic = [term for term in query_match_terms(query) if term in GENERIC_TERMS]
    if required:
        quoted = " ".join(required)
        core = f'"{quoted}"'
        if generic:
            core = f"{core} {' '.join(generic)}"
    else:
        core = query.strip()
    if required and not query_wants_parts(query):
        negatives = " ".join(f"-{word}" for word in ACCESSORY_NEGATIVES)
        core = f"{core} {negatives}"
    return core


def hit_is_plausible(query: str, title: str, snippet: str = "", url: str = "") -> bool:
    """Cheap pre-scrape check: required terms present and not an off-query spare."""
    slug = url.replace("-", " ").replace("/", " ").replace("_", " ")
    blob = f"{title} {snippet} {slug}"
    if missing_required(query, f"{title} {snippet}") and missing_required(query, blob):
        return False
    if accessory_multiplier(query, f"{title} {slug}") < 0.5:
        return False
    lowered = f"{title} {snippet}".lower()
    if not query_wants_parts(query) and any(
        marker in lowered for marker in ("wiki", "guía", "guia completa", "buying guide")
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
