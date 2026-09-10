# Product Finder

Search the web for a product and get **five ranked picks**:

- **Best price** — lowest effective price among reasonably relevant items
- **Best match** — highest combined score of relevance + price + rating
- **Best value** — strongest quality-per-price heuristic
- **Best rated** — highest rating among relevant matches
- **Also consider** — next strongest overall listing (so you always get five answers when enough pages were found)

Use the **web app** for a search box, or the CLI if you prefer the terminal.

## Web app (recommended)

Python 3.10+ is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5055](http://127.0.0.1:5055), type a query such as `wireless earbuds under 200 AED`, and wait 15–30 seconds while FindBest searches Google and other web indexes, then reads product pages.

The app uses the `everywhere` search backend by default (DuckDuckGo’s multi-engine web search plus Google when available).

## CLI

```bash
python main.py --query "wireless earbuds under 200 AED"
python main.py --query "wireless earbuds under 200 AED" --json
```

## Configure the search backend

Set environment variables (or pass `--backend`):

| Variable | Purpose |
| --- | --- |
| `SEARCH_BACKEND` | `everywhere` (web app default), `duckduckgo` (CLI default), `google`, `google_cse`, or `serpapi` |
| `SEARCH_REGION` | DuckDuckGo region, default `ae-en` |
| `SERPAPI_KEY` | Required when `SEARCH_BACKEND=serpapi` |
| `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` | Official Google Programmable Search JSON API |
| `PRODUCT_FINDER_BASE_CURRENCY` | Comparison currency, default `AED` |
| `PRODUCT_FINDER_TIMEOUT` | HTTP timeout in seconds (default `12`) |
| `PRODUCT_FINDER_MAX_PAGES` | Cap on pages scraped per query |
| `PRODUCT_FINDER_WEIGHTS` | JSON object of scoring weights |
| `SCORE_WEIGHT_RELEVANCE` / `SCORE_WEIGHT_PRICE` / `SCORE_WEIGHT_RATING` | Individual weights |

`--backend google` uses Programmable Search when the Google env vars are set; otherwise it falls back to `googlesearch-python`.

Example:

```bash
export SEARCH_BACKEND=duckduckgo
export PRODUCT_FINDER_BASE_CURRENCY=AED
```

## Example commands

```bash
python main.py --query "wireless earbuds under 200 AED"

python main.py --query "wireless earbuds under 200 AED" --max-results 15 --max-pages 8

python main.py --query "noise cancelling headphones" --base-currency USD --json

python main.py --query "office chair under 500 AED" \
  --weights '{"relevance":0.5,"price":0.2,"rating":0.3}' \
  --json-only
```

`--json` prints JSON after the table. `--json-only` prints JSON alone.

## How scoring works

Each item gets three 0–1 component scores, then a weighted overall score:

```
overall = w_relevance * relevance + w_price * price_score + w_rating * rating_score
```

Default weights: relevance `0.45`, price `0.25`, rating `0.30` (normalized to sum to 1).

- **Relevance** — query-term overlap in title (heavier) and description/features, plus a small bonus for an exact phrase match.
- **Price** — log-scaled min–max so *lower is better*, without letting ultra-cheap outliers dominate. Missing prices get a penalty (`0.20`) and are **excluded from Best price**. Over-budget items (when the query says “under 200 AED”) are down-weighted, not dropped.
- **Rating** — `stars / 5`. Missing ratings use a neutral default of **3.5/5** (shown with `*` in the table).

**Best value** is quality per unit of (log) price:

```
quality = 0.55 * relevance + 0.45 * rating_score
value   = quality / (1 + log(1 + price / median_price))
```

Prices are parsed from JSON-LD, Open Graph, microdata, and visible text. Amounts in mixed currencies are converted to the base currency with a **fixed** FX table in `config.py` (no live feed).

Scraping is polite: configurable timeouts/retries, random delays between requests, and a hard cap on pages fetched per query.

## Project layout

| File | Role |
| --- | --- |
| `app.py` | Web app (search box + five ranked cards) |
| `main.py` | CLI (`argparse`), table + JSON output |
| `search.py` | Search backends (`everywhere` merges multiple engines) |
| `scraper.py` | HTTP fetch + HTML / price / rating parsing |
| `scoring.py` | Scoring and category ranking |
| `models.py` | Dataclasses (`ProductItem`, `SearchResult`, …) |
| `config.py` | Weights, timeouts, user-agents, FX rates |
| `templates/` + `static/` | FindBest UI |

The ranking helpers are written so you can later add CSV export, extra categories, or a UI without changing the scrape pipeline.

## Tests

```bash
pytest -q
```
