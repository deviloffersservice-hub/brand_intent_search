"""Settings. Every value can be overridden with an environment variable of the same name."""
import os
from datetime import timedelta, timezone


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


SHEET_ID = os.environ.get("SHEET_ID", "1h3GY7aUPnDZrv1lfYOrG1Oc932SFM843Hb3PFID7Ya4")
BRANDS_TAB = os.environ.get("BRANDS_TAB", "github script for brands")
AGENCIES_TAB = os.environ.get("AGENCIES_TAB", "github script for agencies")
CREATORS_TAB = os.environ.get("CREATORS_TAB", "github script for creators")

MAX_AGE_DAYS = _int("MAX_AGE_DAYS", 14)  # posts, jobs and news older than this are skipped

# Per-run budgets (a run every 3 hours; keep each one short and gentle).
SEARCHES_PER_RUN = _int("SEARCHES_PER_RUN", 30)
SEARCH_GAP_SECONDS = _float("SEARCH_GAP_SECONDS", 20)  # engines rate-limit per time window
MAX_POST_PAGES = _int("MAX_POST_PAGES", 300)  # LinkedIn post pages read per run (~2 s each)
JOB_PAGES_PER_QUERY = _int("JOB_PAGES_PER_QUERY", 10)  # 10 jobs per page; stops early at the target
TARGET_BRANDS = _int("TARGET_BRANDS", 100)  # new brands per run; a run stops looking once it has these
MAX_CONSECUTIVE_BLOCKS = _int("MAX_CONSECUTIVE_BLOCKS", 3)
REQUEST_DELAY_MIN = _float("REQUEST_DELAY_MIN", 1.0)
REQUEST_DELAY_MAX = _float("REQUEST_DELAY_MAX", 2.5)

STATE_FILE = os.environ.get("STATE_FILE", ".state/crawl_queue.json")  # kept between runs (Actions cache)
QUEUE_KEEP = _int("QUEUE_KEEP", 3000)  # unread posts carried to the next run
# LinkedIn adds "More relevant posts" to a post page only after a few days (seen: none at 0-2 days,
# 10 at 3-4 days), so younger posts are crawled last and re-read once they are this old.
RELATED_AFTER_DAYS = _int("RELATED_AFTER_DAYS", 3)

IST = timezone(timedelta(hours=5, minutes=30))
