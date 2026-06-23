"""
CLI entrypoint. Run a scraper by source slug:

    python cli.py olbg

Add new sources here as they're built (Forebet, FreeSuperTips, SoccerVista...).
"""

import asyncio
import sys

from sources.olbg import OLBGScraper
from sources.forebet import ForebetScraper
from utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

SCRAPERS = {
    "olbg": OLBGScraper,
    "forebet": ForebetScraper,        # Task 3
    # "freesupertips": FreeSuperTipsScraper,  # Task 4
    # "soccervista": SoccerVistaScraper,      # Task 4
}


async def run(source_slug: str) -> None:
    scraper_cls = SCRAPERS.get(source_slug)
    if scraper_cls is None:
        logger.error("unknown_source", source=source_slug, available=list(SCRAPERS.keys()))
        sys.exit(1)

    async with scraper_cls() as scraper:
        picks = await scraper.scrape()
        logger.info("run_complete", source=source_slug, picks_published=len(picks))


if __name__ == "__main__":
    configure_logging()
    if len(sys.argv) != 2:
        print("Usage: python cli.py <source_slug>  e.g. python cli.py olbg")
        sys.exit(1)
    asyncio.run(run(sys.argv[1]))
