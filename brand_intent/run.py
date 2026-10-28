"""One run: collect brand asks from LinkedIn jobs, LinkedIn posts, Reddit and news; add new ones to
the brands tab, and the agencies and creators found in their comments to their own tabs.

    python -m brand_intent.run            # writes to the sheet
    python -m brand_intent.run --dry-run  # prints what it would add
"""
from __future__ import annotations

import argparse
import heapq
import logging
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import config, intent, queries
from .linkedin import Blocked, Fetcher, NotFound, POST_URL_RE, activity_id_from_url, activity_time, \
    canonical_post_url, country_name
from .reddit import Reddit, thread_url
from .search import Searcher
from .sheets import fmt_date, fmt_time

log = logging.getLogger("brand_intent")

JOB_TITLE_RE = re.compile(r"influencer|creator|ugc|\bkol\b|brand partnership|talent partnership|"
                          r"linkedin (?:marketing|content|creator|brand|ghost ?writ|influencer)", re.I)


class Collector:
    """New rows for the three tabs, deduplicated against the sheet and within the run."""

    def __init__(self, existing_brands: list[dict], existing_agencies: list[dict], existing_creators: list[dict]):
        self.brand_urls = {r.get("Post / Job URL", "") for r in existing_brands}
        self.job_companies = {r.get("Brand / Company", "").lower() for r in existing_brands
                              if r.get("Source", "").startswith("LinkedIn job")}
        self.people = {r.get("Profile", "") for r in existing_agencies + existing_creators}
        self.brands: list[dict] = []
        self.agencies: list[dict] = []
        self.creators: list[dict] = []
        self.skipped = Counter()

    def add_brand(self, row: dict) -> bool:
        url = row["Post / Job URL"]
        if url in self.brand_urls:
            self.skipped["already in sheet"] += 1
            return False
        self.brand_urls.add(url)
        row["Added At (IST)"] = fmt_time(datetime.now(timezone.utc))
        self.brands.append(row)
        return True

    def add_person(self, kind: str, row: dict) -> bool:
        key = row["Profile"]
        if not key or key in self.people:
            return False
        self.people.add(key)
        row["Added At (IST)"] = fmt_time(datetime.now(timezone.utc))
        (self.agencies if kind == "Agency" else self.creators).append(row)
        return True


def recent(dt: datetime | None, now: datetime) -> bool:
    return dt is not None and now - dt <= timedelta(days=config.MAX_AGE_DAYS)


# --- LinkedIn jobs ------------------------------------------------------------------------------
def collect_jobs(fetcher: Fetcher, out: Collector, now: datetime):
    for kw in queries.JOB_KEYWORDS:
        for loc in queries.JOB_LOCATIONS:
            for page in range(config.JOB_PAGES_PER_QUERY):
                if len(out.brands) >= config.TARGET_BRANDS:
                    return
                try:
                    jobs = fetcher.jobs(kw, loc, start=page * 10)
                except NotFound as e:
                    log.info("jobs %r in %s: %s", kw, loc, e)
                    break
                for job in jobs:
                    if not JOB_TITLE_RE.search(job.title) or not recent(job.posted, now):
                        continue
                    slug_words = job.company_url.rsplit("/", 1)[-1].replace("-", " ")
                    if job.company.lower() == "linkedin" or intent.looks_like_agency(job.company, slug=slug_words):
                        out.skipped["job at an agency"] += 1
                        continue
                    mkt = intent.market("", "", job.location) or ("US" if loc == "United States" else "")
                    if not mkt or job.company.lower() in out.job_companies:
                        continue
                    out.job_companies.add(job.company.lower())
                    out.add_brand({"Brand / Company": job.company, "Company LinkedIn": job.company_url,
                                   "Looking For": "Hiring: " + job.title, "Market": mkt,
                                   "Source": f"LinkedIn job ({job.location})", "Post / Job URL": job.url,
                                   "Posted On": fmt_date(job.posted), "Platforms Mentioned": "",
                                   "Matched Text": job.title})
                if len(jobs) < 10:
                    break


# --- LinkedIn posts -----------------------------------------------------------------------------
def handle_post(fetcher: Fetcher, url: str, out: Collector, now: datetime, found_by: str):
    """Read one post; record it if it's a brand's ask. Returns the post (for its related posts)."""
    post = fetcher.post(url)
    a = post.author
    if not recent(post.published, now):
        out.skipped["post older than 14 days"] += 1
        return post
    looking = intent.wants(post.text)
    if not looking:
        out.skipped["post isn't an ask"] += 1
        return post
    if intent.looks_like_agency(a.name, a.headline):
        # An agency asking for creators for its clients: an agency lead, not a brand.
        out.add_person("Agency", {"Name": a.name, "Profile": a.url, "Headline": a.headline,
                                  "Page Type": "Company page" if a.is_company else "Person",
                                  "Country": country_name(a.country), "Found Via": "Agency's own post",
                                  "Comment / Post": post.text[:500], "Brand": "", "Brand Post URL": post.url})
        out.skipped["poster is an agency"] += 1
        return post
    mkt = intent.market(a.country, post.text)
    if not mkt:
        out.skipped["not India/US"] += 1
        return post
    brand = a.name if a.is_company else intent.company_from_headline(a.headline)
    agencies = creators = 0
    for c in post.comments:
        p = c.author
        kind = intent.commenter_type(p.name, p.headline, p.is_company, c.text)
        if not kind or p.url == a.url:
            continue
        added = out.add_person(kind, {"Name": p.name, "Profile": p.url, "Headline": p.headline,
                                      "Page Type": "Company page" if p.is_company else "Person",
                                      "Country": country_name(p.country), "Found Via": "Comment on brand post",
                                      "Comment / Post": c.text[:500], "Brand": brand or a.name,
                                      "Brand Post URL": post.url})
        agencies += kind == "Agency" and added
        creators += kind == "Creator" and added
    out.add_brand({"Brand / Company": brand, "Company LinkedIn": a.url if a.is_company else "",
                   "Posted By": a.name, "Poster Profile": a.url, "Poster Headline": a.headline,
                   "Looking For": ", ".join(looking), "Platforms Mentioned": ", ".join(intent.platforms(post.text)),
                   "Market": mkt, "Source": f"LinkedIn post ({found_by})", "Post / Job URL": post.url,
                   "Posted On": fmt_date(post.published), "Matched Text": intent.evidence(post.text),
                   "Post Text": post.text[:1500], "Agencies in Comments": agencies, "Creators in Comments": creators})
    return post


# --- Reddit -------------------------------------------------------------------------------------
def handle_reddit(reddit: Reddit, hit, out: Collector, now: datetime):
    t = reddit.thread(hit.url, hit.title, hit.snippet)
    if not t or t.url in out.brand_urls:
        return
    if t.published and not recent(t.published, now):
        out.skipped["post older than 14 days"] += 1
        return
    blob = f"{t.title}. {t.text}"
    looking = intent.wants(blob)
    if not looking:
        out.skipped["post isn't an ask"] += 1
        return
    # India subreddits (r/india, r/IndianStartups, r/IndiaBusiness...) count as Indian posters.
    mkt = intent.market("in" if "india" in t.subreddit.lower() else "", blob)
    if not mkt:
        out.skipped["not India/US"] += 1
        return
    agencies = creators = 0
    for user, body in t.comments:
        kind = intent.reddit_commenter_type(body)
        if kind and out.add_person(kind, {"Name": f"u/{user}", "Profile": f"https://www.reddit.com/user/{user}",
                                          "Page Type": "Reddit user", "Found Via": "Comment on Reddit post",
                                          "Comment / Post": body[:500], "Brand": f"u/{t.author}" if t.author else "",
                                          "Brand Post URL": t.url}):
            agencies += kind == "Agency"
            creators += kind == "Creator"
    out.add_brand({"Brand / Company": "", "Posted By": f"u/{t.author}" if t.author else "",
                   "Poster Profile": f"https://www.reddit.com/user/{t.author}" if t.author else "",
                   "Looking For": ", ".join(looking), "Platforms Mentioned": ", ".join(intent.platforms(blob)),
                   "Market": mkt, "Source": f"Reddit r/{t.subreddit}" + ("" if t.full else " (search snippet)"),
                   "Post / Job URL": t.url, "Posted On": fmt_date(t.published), "Matched Text": intent.evidence(blob),
                   "Post Text": blob[:1500], "Agencies in Comments": agencies, "Creators in Comments": creators})


# --- news ---------------------------------------------------------------------------------------
def handle_news(hit, out: Collector, now: datetime):
    if hit.published and not recent(hit.published, now):
        return
    looking = intent.news_wants(hit.title, hit.snippet)
    mkt = intent.market("", f"{hit.title}. {hit.snippet}")
    if not looking or not mkt:
        out.skipped["news not an ask / not India-US"] += 1
        return
    out.add_brand({"Brand / Company": intent.brand_from_title(hit.title), "Looking For": ", ".join(looking),
                   "Platforms Mentioned": ", ".join(intent.platforms(hit.snippet)), "Market": mkt,
                   "Source": f"News ({hit.source})" if hit.source else "News", "Post / Job URL": hit.url,
                   "Posted On": fmt_date(hit.published), "Matched Text": hit.title,
                   "Post Text": hit.snippet[:1500]})


# A related post worth reading: it is about influencer/creator/agency marketing (or asks for it).
TOPICAL = re.compile(r"influencer|creator|\bugc\b|\bkols?\b|agenc(?:y|ies)|brand (?:deal|collab|partner)|"
                     r"collaborat|campaign|marketing|linkedin", re.I)


class Crawl:
    """LinkedIn post pages, best first: cards whose text already asks for an agency or creators,
    then posts about influencer/creator marketing (for their related posts), then search seeds."""

    def __init__(self, now: datetime):
        self.now = now
        self.heap: list[tuple] = []
        self.queued: set[str] = set()
        self.origin: dict[str, str] = {}
        self.n = 0

    def push(self, url: str, priority: int, origin: str = "related posts"):
        url = canonical_post_url(url)
        aid = activity_id_from_url(url)
        if url in self.queued or (aid and not recent(activity_time(aid), self.now)):
            return  # old posts are skipped without fetching: the date is in the link
        self.queued.add(url)
        self.origin[url] = origin
        self.n += 1
        heapq.heappush(self.heap, (priority, -int(aid or 0), self.n, url))

    def pop(self) -> str | None:
        return heapq.heappop(self.heap)[-1] if self.heap else None

    def add_related(self, post):
        for r in post.related:
            if r.published and not recent(r.published, self.now):
                continue
            if intent.wants(r.text):
                self.push(r.url, 0)
            elif TOPICAL.search(r.text):
                self.push(r.url, 1)


def search_and_read(fetcher: Fetcher, searcher: Searcher, reddit: Reddit, out: Collector, now: datetime, slot: int):
    """Searches (LinkedIn seed posts, Reddit, news), then a crawl of LinkedIn's related posts from
    those seeds. Everything stops once the run has its target."""
    crawl = Crawl(now)
    plan = ([("linkedin", q) for q in queries.rotation(queries.LINKEDIN_POSTS, 10, slot)] +
            [("seed", q) for q in queries.rotation(queries.LINKEDIN_SEEDS, 6, slot)] +
            [("reddit", q) for q in queries.rotation(queries.REDDIT, 4, slot)] +
            [("news", q) for q in queries.rotation(queries.NEWS, 6, slot)])
    for kind, q in plan:
        if len(out.brands) >= config.TARGET_BRANDS:
            break
        if not searcher.alive:
            log.info("search engines stopped answering; ending searches")
            break
        if kind == "news":
            for hit in searcher.news(q, timelimit="w"):
                _safely(handle_news, hit, out, now)
        elif kind == "reddit":
            for hit in searcher.text(f"site:reddit.com {q}", timelimit="w"):
                _safely(handle_reddit, reddit, hit, out, now)
        else:
            for hit in searcher.text(f"site:linkedin.com/posts {q}", timelimit="w" if kind == "seed" else "m"):
                if (m := POST_URL_RE.search(hit.url)):
                    crawl.push(m.group(0), 0 if intent.wants(f"{hit.title} {hit.snippet}") else 2, "search")
    log.info("searches: %d asked, %d answered; %d LinkedIn posts to start from", searcher.asked, searcher.answered,
             len(crawl.heap))

    pages = 0
    while len(out.brands) < config.TARGET_BRANDS and pages < config.MAX_POST_PAGES and (url := crawl.pop()):
        if url in out.brand_urls:
            continue
        pages += 1
        try:
            post = _safely(handle_post, fetcher, url, out, now, crawl.origin.get(url, "related posts"))
        except Blocked as e:
            log.warning("LinkedIn stopped serving posts (%s)", e)
            break
        if post:
            crawl.add_related(post)
        if pages % 50 == 0:
            log.info("crawl: %d posts read, %d brands so far, %d queued", pages, len(out.brands), len(crawl.heap))
    log.info("crawl: %d LinkedIn posts read", pages)


def _safely(fn, *args):
    """One bad page or result must never end the run: a missing page is skipped, an unexpected
    error is logged and skipped. Blocked still propagates, so the caller can stop reading LinkedIn."""
    try:
        return fn(*args)
    except NotFound:
        return None
    except Blocked:
        raise
    except Exception as e:  # unexpected page shape etc.
        log.warning("%s failed: %r", fn.__name__, e)
        return None


def run(dry_run: bool) -> int:
    started = time.time()
    now = datetime.now(timezone.utc)
    book = None
    if dry_run:
        out = Collector([], [], [])
    else:
        from .sheets import Book
        book = Book()
        out = Collector(book.brands.rows(), book.agencies.rows(), book.creators.rows())
    fetcher, searcher, reddit = Fetcher(), Searcher(), Reddit()
    slot = int(time.time() // (3 * 3600))
    try:
        # Brands that say so in a post first; job listings fill up the rest of the target.
        search_and_read(fetcher, searcher, reddit, out, now, slot)
        try:
            collect_jobs(fetcher, out, now)
        except Blocked as e:
            log.warning("LinkedIn refused job searches (%s)", e)
    finally:  # whatever happened, keep what was found
        log.info("new: %d brands (target %d%s), %d agencies, %d creators; skipped: %s", len(out.brands),
                 config.TARGET_BRANDS, "" if len(out.brands) >= config.TARGET_BRANDS
                 else f", short by {config.TARGET_BRANDS - len(out.brands)}",
                 len(out.agencies), len(out.creators), dict(out.skipped.most_common()))
        log.info("brands by source: %s", dict(Counter(r["Source"].split(" (")[0] for r in out.brands)))
        if dry_run:
            for tab, rows in (("BRAND", out.brands), ("AGENCY", out.agencies), ("CREATOR", out.creators)):
                for r in rows:
                    print(tab, {k: v for k, v in r.items() if v not in ("", 0)})
        else:
            book.brands.append(out.brands)
            book.agencies.append(out.agencies)
            book.creators.append(out.creators)
        log.info("done in %.1f minutes", (time.time() - started) / 60)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print instead of writing to the sheet")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(run(args.dry_run))


if __name__ == "__main__":
    main()
