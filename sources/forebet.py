"""
Forebet (forebet.com) scraper.

Forebet provides mathematically-modelled football predictions. Each match row
contains:
  - Fixture (home/away teams) via schema.org microdata — clean, reliable
  - Kickoff datetime as DD/MM/YYYY HH:MM in a .date_bah span
  - Predicted outcome (1 / X / 2) from .forepr
  - Win/draw/away probabilities from .fprc spans (.fpr class = highlighted)
  - Predicted score from .ex_sc.tabonly
  - Average predicted goals from .avg_sc.tabonly
  - Fractional odds from .haodd spans → converted to decimal
  - League short code from .shortTag (no full league name in listing view)
  - Forebet match ID from the #nofav div id attribute

Unlike OLBG, Forebet has no individual tipster identity — every pick comes
from the same algorithmic model. We use "Forebet Model" as tipster_name and
the forebet match ID as tipster_external_id (stable across re-scrapes, unlike
OLBG's tip_hash-per-tip pattern).

Market mapping: Forebet only predicts 1X2 (match result) on the listing page,
so all picks use MarketType.MATCH_RESULT. The confidence score maps to the
highlighted win-probability percentage (the span with class="fpr").

Run via: python cli.py forebet
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from playwright.async_api import Page

from config import settings
from models.pick import MarketType, RawPick
from sources.base_scraper import BaseSourceScraper
from utils.jitter import human_scroll, jitter_delay
from utils.logger import get_logger

logger = get_logger(__name__)

# Verified against forebet.com/en/football-tips-and-predictions-for-today (Jun 2026)
FOREBET_LISTING_PATH = "/en/football-tips-and-predictions-for-today"

# Selectors — verified against live DOM snapshot
SEL_MATCH_ROW = "div.rcnt"
SEL_HOME_TEAM = "span.homeTeam span[itemprop='name']"
SEL_AWAY_TEAM = "span.awayTeam span[itemprop='name']"
SEL_KICKOFF = "span.date_bah"
SEL_MATCH_LINK = "a.tnmscn"
SEL_LEAGUE_CODE = "span.shortTag"
SEL_PREDICTION = "span.forepr span"      # 1, X, or 2
SEL_PREDICTED_SCORE = "div.ex_sc.tabonly"
SEL_AVG_GOALS = "div.avg_sc.tabonly"
SEL_PROBS = "div.fprc span"              # three spans: home%, draw%, away%
SEL_ODDS = "div.haodd span"             # 6 spans: H/D/A odds then metadata
SEL_MATCH_ID = "div.nofav"              # id attribute = forebet match id

FOREBET_TIPSTER_NAME = "Forebet Model"

# Predicted outcome code → selection label stored in picks.selection
_OUTCOME_MAP: dict[str, str] = {
    "1": "Home",
    "X": "Draw",
    "2": "Away",
}

# Index into the haodd odds spans for each predicted outcome
_ODDS_IDX: dict[str, int] = {"1": 0, "X": 1, "2": 2}


def _fractional_to_decimal(frac: str) -> Decimal | None:
    """
    Convert Forebet fractional odds ("5/2", "3/4") to decimal.
    Forebet uses "no" and "down" as placeholders for unavailable odds —
    both return None rather than raising or defaulting to a magic number.
    """
    frac = frac.strip().lower()
    if frac in ("no", "down", "", "-"):
        return None
    try:
        if "/" in frac:
            num, denom = frac.split("/", 1)
            return (Decimal(num) / Decimal(denom) + Decimal("1")).quantize(Decimal("0.001"))
        return Decimal(frac).quantize(Decimal("0.001"))
    except (InvalidOperation, ZeroDivisionError, ValueError):
        return None


def _parse_forebet_kickoff(text: str) -> datetime | None:
    """
    Parse Forebet's DD/MM/YYYY HH:MM kickoff string into UTC.
    Forebet displays kickoff times in venue-local time — we store them as-is
    (treated as UTC) since venue timezone is not available in the listing view.
    This is a known approximation; flagged here for future TZ-aware handling.
    """
    try:
        return datetime.strptime(text.strip(), "%d/%m/%Y %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class ForebetScraper(BaseSourceScraper):
    source_slug = "forebet"

    def __init__(self) -> None:
        super().__init__()
        self.base_url = "https://www.forebet.com"
        self.listing_url = f"{self.base_url}{FOREBET_LISTING_PATH}"

    async def scrape(self) -> list[RawPick]:
        page = await self.new_stealth_page()
        picks: list[RawPick] = []

        try:
            await self.goto_with_retry(page, self.listing_url)
            await self._dismiss_cookie_banner(page)
            await human_scroll(page, distance_px=2000, steps=12)
            await jitter_delay(1.0, 2.0)

            rows = await page.query_selector_all(SEL_MATCH_ROW)
            logger.info("forebet_rows_found", count=len(rows), source=self.source_slug)

            for row in rows:
                try:
                    pick = await self._parse_row(row)
                    if pick is not None:
                        picks.append(pick)
                        await self.publish_pick(pick)
                except Exception:
                    logger.exception("forebet_row_parse_failed", source=self.source_slug)

            if not picks:
                logger.error(
                    "forebet_scrape_yielded_zero_picks",
                    source=self.source_slug,
                    msg="No picks extracted — check for selector drift or anti-bot block",
                )

        finally:
            await page.close()

        logger.info("scrape_complete", source=self.source_slug, picks_found=len(picks))
        return picks

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        """Forebet uses Cookiebot — try known selectors, non-fatal if absent."""
        for selector in (
            "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "button[id*='accept']",
            "button[class*='accept']",
        ):
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await jitter_delay(0.5, 1.2)
                    await btn.click()
                    await page.wait_for_timeout(800)
                    return
            except Exception:  # noqa: BLE001
                continue

    async def _parse_row(self, row) -> RawPick | None:
        # --- Teams (schema.org microdata — most reliable field on the page) ---
        home_el = await row.query_selector(SEL_HOME_TEAM)
        away_el = await row.query_selector(SEL_AWAY_TEAM)
        if home_el is None or away_el is None:
            return None
        home_team = (await home_el.inner_text()).strip()
        away_team = (await away_el.inner_text()).strip()
        if not home_team or not away_team:
            return None

        # --- Match ID (stable forebet identifier → tipster_external_id) ---
        # Using the match ID (not a hash) means re-scraping the same fixture
        # will always produce the same tipster_external_id, unlike OLBG's
        # tip_hash-per-tip pattern. This IS the dedup key downstream.
        match_id_el = await row.query_selector(SEL_MATCH_ID)
        match_id: str | None = None
        if match_id_el is not None:
            match_id = await match_id_el.get_attribute("id")
        if not match_id:
            link_el = await row.query_selector(SEL_MATCH_LINK)
            if link_el is not None:
                href = await link_el.get_attribute("href") or ""
                match_id = href.rstrip("/").split("/")[-1]
        if not match_id:
            logger.warning(
                "forebet_missing_match_id",
                home=home_team,
                away=away_team,
                source=self.source_slug,
            )
            return None

        # --- Kickoff ---
        kickoff_el = await row.query_selector(SEL_KICKOFF)
        kickoff_utc = None
        if kickoff_el is not None:
            kickoff_utc = _parse_forebet_kickoff(await kickoff_el.inner_text())

        # --- League short code ---
        league_el = await row.query_selector(SEL_LEAGUE_CODE)
        league_name = (await league_el.inner_text()).strip() if league_el else None

        # --- Predicted outcome (1 / X / 2) ---
        pred_el = await row.query_selector(SEL_PREDICTION)
        if pred_el is None:
            logger.warning(
                "forebet_missing_prediction",
                home=home_team,
                away=away_team,
                source=self.source_slug,
            )
            return None
        outcome_code = (await pred_el.inner_text()).strip()
        selection = _OUTCOME_MAP.get(outcome_code)
        if selection is None:
            logger.warning(
                "forebet_unmapped_outcome",
                outcome=outcome_code,
                home=home_team,
                away=away_team,
                source=self.source_slug,
            )
            return None

        # --- Confidence: the highlighted probability span (.fpr class) ---
        confidence: Decimal | None = None
        for el in await row.query_selector_all(SEL_PROBS):
            if "fpr" in (await el.get_attribute("class") or ""):
                try:
                    confidence = Decimal((await el.inner_text()).strip())
                except InvalidOperation:
                    pass
                break

        # --- Decimal odds for the predicted outcome ---
        # haodd spans: [home_frac, draw_frac, away_frac, meta, meta, meta]
        odds_decimal: Decimal | None = None
        odds_els = await row.query_selector_all(SEL_ODDS)
        if len(odds_els) >= 3:
            outcome_odds_idx = _ODDS_IDX.get(outcome_code, 0)
            frac_text = (await odds_els[outcome_odds_idx].inner_text()).strip()
            odds_decimal = _fractional_to_decimal(frac_text)

        # --- Raw text for human-readable context ---
        score_el = await row.query_selector(SEL_PREDICTED_SCORE)
        avg_el = await row.query_selector(SEL_AVG_GOALS)
        pred_score = (await score_el.inner_text()).strip() if score_el else ""
        avg_goals = (await avg_el.inner_text()).strip() if avg_el else ""

        raw_text = " | ".join(
            part for part in [
                f"{home_team} vs {away_team}",
                f"Prediction: {outcome_code} ({selection})",
                f"Score: {pred_score}" if pred_score else "",
                f"Avg goals: {avg_goals}" if avg_goals else "",
                f"Confidence: {confidence}%" if confidence else "",
            ]
            if part
        )

        return RawPick(
            source_slug=self.source_slug,
            tipster_external_id=match_id,
            tipster_name=FOREBET_TIPSTER_NAME,
            home_team_name=home_team,
            away_team_name=away_team,
            league_name=league_name,
            kickoff_utc=kickoff_utc,
            market=MarketType.MATCH_RESULT,
            selection=selection,
            odds_decimal=odds_decimal,
            confidence=confidence,
            raw_text=raw_text,
            posted_at=kickoff_utc or datetime.now(timezone.utc),
        )
