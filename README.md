# Scraper Service — Betting Tipster Aggregator

Python + Playwright scrapers for the tipster/statistical sources. Task 2 ships
the OLBG module; Forebet, FreeSuperTips and SoccerVista follow in Tasks 3–4
using this same `BaseSourceScraper` pattern.

## Setup

```bash
cd scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Fill in PROXY_HOST / PROXY_USERNAME / PROXY_PASSWORD from your
# Webshare or Bright Data residential proxy dashboard.
```

Redis must be running locally (or `REDIS_URL` pointed at your instance):

```bash
docker run -d -p 6379:6379 redis:7-alpine
```

## Running

```bash
python cli.py olbg
```

First run with `SCRAPE_HEADLESS=false` in `.env` so you can watch the browser
and confirm selectors against the live page.

## OLBG scraping notes

The OLBG scraper targets `https://www.olbg.com/betting-tips/Football/1`
(configurable via `OLBG_BASE_URL`). Tips are extracted from embedded JSON in
the page HTML (primary path), with a DOM fallback if that payload is missing.

Listing rows are community-popular selections (not individual tipster cards).
Each pick uses `tip_hash` as `tipster_external_id` and `"OLBG Popular"` as
`tipster_name`. Unmapped markets are skipped rather than defaulted.

Before your first real run:

1. Set `SCRAPE_HEADLESS=false`, run `python cli.py olbg`, and confirm the
   listing loads through your proxy.
2. Check logs for `unmapped_market_label` warnings and extend
   `MARKET_LABEL_MAP` in `sources/olbg.py` if needed.
3. Confirm your proxy provider's sticky-session username format in
   `utils/proxy.py::_build_username`.

Run unit tests: `pytest tests/`

For development, install test tooling:

```bash
git clone ...
cd tipster
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium
```

## CI

A GitHub Actions workflow has been added at `.github/workflows/python-ci.yml`.
It installs runtime and dev dependencies, runs `pytest`, and checks code with `ruff`.

## Docker Compose (Recommended for Development)

A full local stack with Redis + TimescaleDB is provided:

```bash
docker compose up -d
# Wait for postgres to be ready, then initialize schema:
docker compose exec postgres psql -U postgres -d tippster -f /app/sql/schema.sql
```

Then run scrapers/processor inside the container or on host.

## Architecture notes

- `sources/base_scraper.py` — shared browser lifecycle, stealth patching,
  proxy config, retry-with-backoff, and cookie/session persistence
  (`.storage_state/<source>.json`) so each run resumes as a returning visitor.
- `models/pick.py` — typed contract pushed onto Redis; the processor (Task 5)
  resolves `fixture_id`/`tipster_id` and writes to Postgres using
  `ON CONFLICT (fixture_id, tipster_id, market, selection) DO UPDATE`,
  since the schema's dedup index no longer includes `posted_at`.
- Dead-letter queue: Failed picks go to `queue:picks:failed` (see `processor/consumer.py`).
- `utils/jitter.py` — randomised delays and scroll behaviour between actions.
- `utils/proxy.py` — sticky residential-proxy session per scrape run.

## Dead Letter Queue (DLQ)

Failed picks (invalid JSON, processing errors after retries) are moved to `queue:picks:failed`.

Replay them with:

```bash
python scripts/replay_dlq.py --limit 20
```

## Adding a new source (Forebet, FreeSuperTips, SoccerVista — Tasks 3–4)

1. Create `sources/<name>.py`, subclass `BaseSourceScraper`.
2. Set `source_slug` and `base_url`.
3. Implement `scrape()` returning `list[RawPick]`, publishing each pick via
   `self.publish_pick(pick)` as you find it (don't batch to the end — if the
   run dies partway through, you keep what was already published).
4. Register it in `cli.py`'s `SCRAPERS` dict.
