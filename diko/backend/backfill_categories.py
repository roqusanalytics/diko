"""One-time backfill: categorize existing transcripts that have summaries."""

import asyncio
import logging
import sys
import time

import database as db
import summarizer
from categorizer import parse_categories_from_response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DELAY_BETWEEN_CALLS = 1.0  # seconds, avoid rate limits


async def backfill():
    settings = db.get_settings()
    if not settings.openrouter_api_key:
        logger.error("No OpenRouter API key configured. Set it in Settings first.")
        sys.exit(1)

    conn = db._get_conn()
    rows = conn.execute(
        """SELECT video_id, title, summary
           FROM transcripts
           WHERE summary != '' AND summary IS NOT NULL
             AND (category_status = '' OR category_status IS NULL)
           ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()

    total = len(rows)
    if total == 0:
        logger.info("No transcripts need categorization. All done!")
        return

    logger.info(f"Found {total} transcripts to categorize.")

    success = 0
    failed = 0
    for i, row in enumerate(rows, 1):
        vid = row["video_id"]
        title = row["title"]
        summary_text = row["summary"]

        logger.info(f"[{i}/{total}] {title[:60]}...")
        db.update_category_status(vid, "pending")

        try:
            result = await summarizer.summarize(
                summary_text,
                settings.openrouter_api_key,
                settings.openrouter_model,
            )
            # The summarizer now returns categories from the combined prompt.
            # For backfill, we just need the categories, not a new summary.
            db.update_categories(vid, result.categories, "done")
            logger.info(f"  -> {result.categories}")
            success += 1
        except Exception as e:
            logger.warning(f"  -> FAILED: {e}")
            db.update_category_status(vid, "failed")
            failed += 1

        if i < total:
            time.sleep(DELAY_BETWEEN_CALLS)

    logger.info(f"Backfill complete: {success} categorized, {failed} failed.")


if __name__ == "__main__":
    asyncio.run(backfill())
