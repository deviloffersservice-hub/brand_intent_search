"""One run: collect brand asks from LinkedIn jobs, LinkedIn posts, Reddit and news; add new ones to
the brands tab, and the agencies and creators found in their comments to their own tabs.

    python -m brand_intent.run            # writes to the sheet
    python -m brand_intent.run --dry-run  # prints what it would add
"""
from __future__ import annotations

import argparse
import heapq
import json
import logging
import os
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

SIGNAL_ASK = "Direct ask"
SIGNAL_INFLUENCER_JOB = "Hiring for influencer marketing"
SIGNAL_CAMPAIGN = "Running influencer campaign"
SIGNAL_MARKETING_JOB = "Hiring for marketing"

PRIORITY = {SIGNAL_ASK: 1, SIGNAL_CAMPAIGN: 2, SIGNAL_INFLUENCER_JOB: 3, SIGNAL_MARKETING_JOB: 4}
# An in-house "Content Creator" job is marketing hiring, not influencer marketing.
IN_HOUSE_CREATOR = re.compile(r"(?:content|video|ugc|reels?|social(?: media)?(?: content)?|digital|on-camera|short-form|"
                              r"ai|junior|senior|youtube)?\s*(?:content )?creators?\b(?! (?:partnerships?|marketing|relations|"
                              r"programs?|community|success|activation|management|campaigns?|economy|operations|strategy))",
                              re.I)
INFLUENCER_ROLE = re.compile(r"influencer|\bkol\b|creator (?:partnerships?|marketing|relations|programs?|community|"
                             r"success|activation|management|campaigns?|operations|strategy)|creators? (?:&|and) "
                             r"(?:influencer|affiliate)|head of creators|director, creators|talent partnership|"
                             r"brand partnership|linkedin|"
                             # managing creators: "Creator & Community", "Creator Commerce", "Social & Creators Lead"
                             r"(?<!content )(?<!video )(?<!reel )(?<!ugc )(?<!camera )(?<!sports )\bcreators? "
                             r"(?:&|and|commerce|live)(?=\s|$)(?! (?:host|editor|presenter|producer))|"
                             r"\b(?:social|community|commerce),? (?:&|and)? ?creators?\b(?! & host)", re.I)


def job_signal(title: str, marketing_search: bool) -> str:
    if marketing_search or (IN_HOUSE_CREATOR.search(title) and not INFLUENCER_ROLE.search(title)):
        return SIGNAL_MARKETING_JOB
    return SIGNAL_INFLUENCER_JOB


def why_kept(r: dict, unsure: bool = False) -> str:
    """A short rationale for keeping a brand row, from its signal and evidence."""
    brand = r.get("Brand / Company") or r.get("Posted By") or "The poster"
    sig, what = r.get("Signal", ""), r.get("Looking For", "")
    src = r.get("Source", "")
    place = src[src.find("(") + 1:-1] if src.startswith("LinkedIn job") and "(" in src else r.get("Market", "")
    if sig == SIGNAL_ASK:
        text = (f"{brand} asks for {what.lower()} in its own words (see Matched Text), and it's in the "
                f"{r.get('Market', '')} market.")
    elif sig == SIGNAL_CAMPAIGN:
        text = f"{brand} is a brand already doing creator/influencer marketing ({what.lower()}), so it may buy more."
    elif sig == SIGNAL_INFLUENCER_JOB:
        text = (f"{brand} is a brand (not an agency or recruiter) hiring for '{what.removeprefix('Hiring: ')}' in "
                f"{place}: it runs influencer/creator marketing.")
    else:
        text = (f"{brand} is a brand (not an agency or recruiter) hiring for '{what.removeprefix('Hiring: ')}' in "
                f"{place}: it is investing in marketing (broader signal).")
    if unsure:
        text += " The name alone doesn't rule out an agency, so it's worth a quick check."
    return text


JOB_TITLE_RE = re.compile(r"influencer|creator|ugc|\bkol\b|brand partnership|talent partnership|"
                          r"linkedin (?:marketing|content|creator|brand|ghost ?writ|influencer)", re.I)


def url_key(url: str) -> str:
    """The same post/job/thread written differently (encoding, case, trailing '/', tracking suffix,
    ugcPost vs activity) gets the same key."""
    url = (url or "").strip()
    if (aid := activity_id_from_url(url) or (re.search(r"ugcPost[-:](\d{15,})", url) or [None, None])[1]):
        return f"li:{aid}"
    if (m := re.search(r"linkedin\.com/jobs/view/[^?#]*?(\d{6,})/?(?:[?#]|$)", url)):
        return f"job:{m.group(1)}"
    if (t := thread_url(url)):
        return f"reddit:{t[2].lower()}"
    return re.sub(r"^https?://(?:www\.)?", "", url.lower()).rstrip("/").split("?")[0]


def company_keys(name: str, company_url: str = "") -> set[str]:
    """A company from a job: its LinkedIn page slug and its name without 'Ltd'/'Limited'/'Pvt'...,
    so 'Honasa Consumer Ltd' and 'Honasa Consumer Limited' match. Two different companies with the
    same name but different pages are told apart by the page."""
    keys = set()
    if "/company/" in company_url:
        keys.add("page:" + company_url.rstrip("/").rsplit("/company/", 1)[-1].lower())
    name = re.sub(r"\b(?:pvt|private|ltd|limited|llp|llc|inc|corp|corporation|co)\b\.?", "", name.lower())
    if (name := re.sub(r"[^a-z0-9]+", " ", name).strip()):
        keys.add("name:" + name)
    return keys


class Collector:
    """New rows for the three tabs, deduplicated against the sheet and within the run."""

    def __init__(self, existing_brands: list[dict], existing_agencies: list[dict], existing_creators: list[dict],
                 removed: list[dict] = ()):
        # Rows taken out on review count as known, so they're never added again.
        existing_brands = list(existing_brands) + [r for r in removed if r.get("From Tab", "").endswith("brands")]
        self.brand_urls = {url_key(r.get("Post / Job URL", "")) for r in existing_brands} - {""}
        # (page, name) key pairs of companies already listed from jobs
        self.job_companies = [company_keys(r.get("Brand / Company", ""), r.get("Company LinkedIn", ""))
                              for r in existing_brands if r.get("Source", "").startswith("LinkedIn job")]
        self.news_brands = {r.get("Brand / Company", "").lower() for r in existing_brands
                            if r.get("Source", "").startswith("News") and r.get("Brand / Company")}
        self.people = {r.get("Profile", "").lower().rstrip("/") for r in existing_agencies + existing_creators}
        self.brands: list[dict] = []
        self.agencies: list[dict] = []
        self.creators: list[dict] = []
        self.skipped = Counter()

    def company_listed(self, name: str, company_url: str) -> bool:
        """Same page, or same name where either side has no page."""
        new = company_keys(name, company_url)
        new_page = {k for k in new if k.startswith("page:")}
        for old in self.job_companies:
            old_page = {k for k in old if k.startswith("page:")}
            if (new_page & old_page) or ((not new_page or not old_page) and (new & old)):
                return True
        return False

    def seen(self, url: str) -> bool:
        return url_key(url) in self.brand_urls

    def add_brand(self, row: dict) -> bool:
        key = url_key(row["Post / Job URL"])
        if key in self.brand_urls:
            self.skipped["already in sheet"] += 1
            return False
        self.brand_urls.add(key)
        row["Priority"] = PRIORITY.get(row.get("Signal", ""), 9)
        row.setdefault("Why Kept", "Added by the script's rules: " + why_kept(row))
        row["Added At (IST)"] = fmt_time(datetime.now(timezone.utc))
        self.brands.append(row)
        return True

    def add_person(self, kind: str, row: dict) -> bool:
        key = row["Profile"].lower().rstrip("/")
        if not key or key in self.people:
            return False
        self.people.add(key)
        row["Added At (IST)"] = fmt_time(datetime.now(timezone.utc))
        (self.agencies if kind == "Agency" else self.creators).append(row)
        return True


def recent(dt: datetime | None, now: datetime) -> bool:
    return dt is not None and now - dt <= timedelta(days=config.MAX_AGE_DAYS)


# --- LinkedIn jobs ------------------------------------------------------------------------------
def collect_jobs(fetcher: Fetcher, out: Collector, now: datetime, marketing: bool = False):
    """Influencer/creator job ads (marketing=False), or, to fill up the target, any marketing job ad."""
    keywords = queries.MARKETING_JOB_KEYWORDS if marketing else queries.JOB_KEYWORDS
    title_re = intent.MARKETING_JOB_TITLE if marketing else JOB_TITLE_RE
    for kw in keywords:
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
                    if not title_re.search(job.title) or not recent(job.posted, now):
                        continue
                    slug_words = job.company_url.rsplit("/", 1)[-1].replace("-", " ")
                    if job.company.lower() == "linkedin" or intent.looks_like_agency(job.company, slug=slug_words):
                        out.skipped["job at an agency"] += 1
                        continue
                    mkt = intent.market("", "", job.location) or ("US" if loc == "United States" else "")
                    if not mkt or out.company_listed(job.company, job.company_url):
                        continue
                    out.job_companies.append(company_keys(job.company, job.company_url))
                    why = (f"Hiring a {job.title} in {job.location} (job posted {fmt_date(job.posted)}): "
                           + ("investing in marketing." if job_signal(job.title, marketing) == SIGNAL_MARKETING_JOB
                              else "building influencer/creator marketing."))
                    out.add_brand({"Brand / Company": job.company, "Company LinkedIn": job.company_url,
                                   "Signal": job_signal(job.title, marketing),
                                   "Why Added": why, "Looking For": "Hiring: " + job.title, "Market": mkt,
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
        campaign = intent.campaign_signal(post.text) if a.is_company else ""
        if campaign and not intent.looks_like_agency(a.name) and (mkt := intent.market(a.country, post.text)):
            out.add_brand({"Brand / Company": a.name, "Signal": SIGNAL_CAMPAIGN,
                           "Why Added": f"{campaign}: the brand's own LinkedIn post on {fmt_date(post.published)} "
                                        f"says \"{intent.CAMPAIGN.search(post.text).group(0)}\".",
                           "Company LinkedIn": a.url, "Posted By": a.name, "Poster Profile": a.url,
                           "Looking For": campaign, "Platforms Mentioned": ", ".join(intent.platforms(post.text)),
                           "Market": mkt, "Source": f"LinkedIn post ({found_by})", "Post / Job URL": post.url,
                           "Posted On": fmt_date(post.published),
                           "Matched Text": intent.CAMPAIGN.search(post.text).group(0), "Post Text": post.text[:1500]})
            return post
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
        kind = intent.commenter_type(p.name, p.headline, p.is_company, c.text, looking)
        if not kind or p.url == a.url:
            continue
        agencies += kind == "Agency"  # everyone who replied, even if already listed from another post
        creators += kind == "Creator"
        out.add_person(kind, {"Name": p.name, "Profile": p.url, "Headline": p.headline,
                              "Page Type": "Company page" if p.is_company else "Person",
                              "Country": country_name(p.country), "Found Via": "Comment on brand post",
                              "Comment / Post": c.text[:500], "Brand": brand or a.name, "Brand Post URL": post.url})
    out.add_brand({"Brand / Company": brand, "Signal": SIGNAL_ASK,
                   "Why Added": f"Posted on LinkedIn on {fmt_date(post.published)} asking for "
                                f"{', '.join(looking).lower()}: \"{intent.evidence(post.text)}\".",
                   "Company LinkedIn": a.url if a.is_company else "",
                   "Posted By": a.name, "Poster Profile": a.url, "Poster Headline": a.headline,
                   "Looking For": ", ".join(looking), "Platforms Mentioned": ", ".join(intent.platforms(post.text)),
                   "Market": mkt, "Source": f"LinkedIn post ({found_by})", "Post / Job URL": post.url,
                   "Posted On": fmt_date(post.published), "Matched Text": intent.evidence(post.text),
                   "Post Text": post.text[:1500], "Agencies in Comments": agencies, "Creators in Comments": creators})
    return post


# --- Reddit -------------------------------------------------------------------------------------
def handle_reddit(reddit: Reddit, hit, out: Collector, now: datetime):
    t = reddit.thread(hit.url, hit.title, hit.snippet)
    if not t or out.seen(t.url):
        return
    if not recent(t.published, now):  # also when the date is unknown: the 14-day rule is strict
        out.skipped["post older than 14 days or undated"] += 1
        return
    blob = f"{t.title}. {t.text}"
    looking = intent.wants(blob)
    if not looking:
        out.skipped["post isn't an ask"] += 1
        return
    # India subreddits (r/india, r/IndianStartups, r/IndiaBusiness...) count as Indian posters.
    mkt = intent.market("in" if re.search(r"india(?!na)", t.subreddit, re.I) else "", blob)
    if not mkt:
        out.skipped["not India/US"] += 1
        return
    agencies = creators = 0
    for user, body in t.comments:
        kind = intent.reddit_commenter_type(body)
        if not kind:
            continue
        agencies += kind == "Agency"
        creators += kind == "Creator"
        out.add_person(kind, {"Name": f"u/{user}", "Profile": f"https://www.reddit.com/user/{user}",
                              "Page Type": "Reddit user", "Found Via": "Comment on Reddit post",
                              "Comment / Post": body[:500], "Brand": f"u/{t.author}" if t.author else "",
                              "Brand Post URL": t.url})
    out.add_brand({"Brand / Company": "", "Signal": SIGNAL_ASK,
                   "Why Added": f"Asked on Reddit r/{t.subreddit} on {fmt_date(t.published)} for "
                                f"{', '.join(looking).lower()}: \"{intent.evidence(blob)}\".",
                   "Posted By": f"u/{t.author}" if t.author else "",
                   "Poster Profile": f"https://www.reddit.com/user/{t.author}" if t.author else "",
                   "Looking For": ", ".join(looking), "Platforms Mentioned": ", ".join(intent.platforms(blob)),
                   "Market": mkt, "Source": f"Reddit r/{t.subreddit}" + ("" if t.full else " (search snippet)"),
                   "Post / Job URL": t.url, "Posted On": fmt_date(t.published), "Matched Text": intent.evidence(blob),
                   "Post Text": blob[:1500], "Agencies in Comments": agencies, "Creators in Comments": creators})


# --- news ---------------------------------------------------------------------------------------
def handle_news(hit, out: Collector, now: datetime):
    if not recent(hit.published, now):  # also when the date is unknown
        out.skipped["news older than 14 days or undated"] += 1
        return
    looking = intent.news_wants(hit.title, hit.snippet)
    campaign = "" if looking else intent.campaign_signal(f"{hit.title}. {hit.snippet}")
    mkt = intent.market("", f"{hit.title}. {hit.snippet}")
    if not (looking or campaign) or not mkt:
        out.skipped["news not an ask / not India-US"] += 1
        return
    brand = intent.brand_from_title(hit.title)
    if brand and intent.looks_like_agency(brand):
        out.skipped["news about an agency"] += 1
        return
    if brand and brand.lower() in out.news_brands:  # the same story from another outlet
        out.skipped["news: same brand already listed"] += 1
        return
    if brand:
        out.news_brands.add(brand.lower())
    source = f"News ({hit.source})" if hit.source else "News"
    if looking:
        signal, why = SIGNAL_ASK, f"{source} on {fmt_date(hit.published)}: \"{hit.title}\"."
    else:
        signal, why = SIGNAL_CAMPAIGN, f"{campaign} ({source}, {fmt_date(hit.published)}): \"{hit.title}\"."
    out.add_brand({"Brand / Company": brand, "Signal": signal, "Why Added": why,
                   "Looking For": ", ".join(looking) or campaign,
                   "Platforms Mentioned": ", ".join(intent.platforms(hit.snippet)), "Market": mkt,
                   "Source": source, "Post / Job URL": hit.url,
                   "Posted On": fmt_date(hit.published), "Matched Text": hit.title,
                   "Post Text": hit.snippet[:1500]})


# A related post worth reading: it is about influencer/creator/agency marketing (or asks for it).
TOPICAL = re.compile(r"influencer|creator|\bugc\b|\bkols?\b|agenc(?:y|ies)|brand (?:deal|collab|partner)|"
                     r"collaborat|campaign|marketing|linkedin", re.I)


class Crawl:
    """LinkedIn post pages, best first: cards whose text already asks for an agency or creators (0),
    posts about influencer/creator marketing (1), search seeds (2), and posts too young to show
    related posts yet (3: still read for their own text, and re-read later for their related posts)."""

    def __init__(self, now: datetime):
        self.now = now
        self.heap: list[tuple] = []
        self.queued: set[str] = set()
        self.origin: dict[str, str] = {}
        self.later: dict[str, int] = {}  # url -> unix time it will be old enough to show related posts
        self.n = 0
        self.cards = Counter()  # what happened to related-post cards (for the log)

    def age_days(self, url: str) -> float | None:
        aid = activity_id_from_url(url)
        return (self.now - activity_time(aid)).total_seconds() / 86400 if aid else None

    def push(self, url: str, priority: int, origin: str = "related posts"):
        url = canonical_post_url(url)
        aid = activity_id_from_url(url)
        if url_key(url) in self.queued or (aid and not recent(activity_time(aid), self.now)):
            return  # old posts are skipped without fetching: the date is in the link
        if priority >= 1 and (age := self.age_days(url)) is not None and age < config.RELATED_AFTER_DAYS:
            priority = 3
        self.queued.add(url_key(url))
        self.origin[url_key(url)] = origin
        self.n += 1
        heapq.heappush(self.heap, (priority, -int(aid or 0), self.n, url))

    def pop(self) -> str | None:
        return heapq.heappop(self.heap)[-1] if self.heap else None

    # Some GitHub machines are served post pages without "More relevant posts", which would leave
    # the crawl with nothing to read; the unread queue is kept between runs so it never starts empty.
    def read_later(self, post_url_: str):
        """A post read before LinkedIn showed its related posts: read it again once it's old enough."""
        aid = activity_id_from_url(post_url_)
        if aid:
            ready = activity_time(aid).timestamp() + config.RELATED_AFTER_DAYS * 86400
            if ready > self.now.timestamp():
                self.later[canonical_post_url(post_url_)] = int(ready)

    def load(self, path: str):
        try:
            with open(path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return
        if isinstance(saved, list):  # older format: just the queue
            saved = {"queue": saved}
        for priority, url, origin in saved.get("queue", []):
            self.push(url, int(priority), origin)
        now = self.now.timestamp()
        for url, ready in saved.get("later", []):
            if ready <= now:
                self.push(url, 1, "related posts")  # old enough now: read again for its related posts
            elif recent(activity_time(activity_id_from_url(url)), self.now):
                self.later[url] = ready
        log.info("crawl: %d posts carried over from earlier runs (%d more waiting to be old enough)",
                 len(self.heap), len(self.later))

    def save(self, path: str):
        keep = [[p, url, self.origin.get(url_key(url), "related posts")]
                for p, _, _, url in sorted(self.heap)[: config.QUEUE_KEEP]]
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump({"queue": keep, "later": sorted(self.later.items())[: config.QUEUE_KEEP]}, f)

    def add_related(self, post):
        for r in post.related:
            if r.published and not recent(r.published, self.now):
                self.cards["older than 14 days"] += 1
            elif intent.wants(r.text):
                self.cards["asks"] += 1
                self.push(r.url, 0)
            elif TOPICAL.search(r.text):
                self.cards["on topic"] += 1
                self.push(r.url, 1)
            else:
                self.cards["off topic" if r.text else "no text"] += 1


def search_and_read(fetcher: Fetcher, searcher: Searcher, reddit: Reddit, out: Collector, now: datetime, slot: int,
                    save_state: bool = False):
    """Searches (LinkedIn seed posts, Reddit, news), then a crawl of LinkedIn's related posts from
    those seeds. Everything stops once the run has its target."""
    crawl = Crawl(now)
    if save_state:
        crawl.load(config.STATE_FILE)
    # Topical seeds and news answer most often, so they go first; exact-ask phrases rarely do.
    plan = ([("seed", q) for q in queries.rotation(queries.LINKEDIN_SEEDS, 8, slot)] +
            [("news", q) for q in queries.rotation(queries.NEWS, 6, slot)] +
            [("news", q) for q in queries.rotation(queries.CAMPAIGN_NEWS, 4, slot)] +
            [("reddit", q) for q in queries.rotation(queries.REDDIT, 4, slot)] +
            [("linkedin", q) for q in queries.rotation(queries.LINKEDIN_POSTS, 8, slot)])
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
            # A month back, not a week: 3-14 day old posts show related posts; older ones are dropped.
            for hit in searcher.text(f"site:linkedin.com/posts {q}", timelimit="m"):
                if (m := POST_URL_RE.search(hit.url)):
                    crawl.push(m.group(0), 0 if intent.wants(f"{hit.title} {hit.snippet}") else 2, "search")
    log.info("searches: %d asked, %d answered; %d LinkedIn posts to start from", searcher.asked, searcher.answered,
             len(crawl.heap))

    pages = with_related = 0
    while len(out.brands) < config.TARGET_BRANDS and pages < config.MAX_POST_PAGES and (url := crawl.pop()):
        if out.seen(url):
            continue
        pages += 1
        try:
            post = _safely(handle_post, fetcher, url, out, now, crawl.origin.get(url_key(url), "related posts"))
        except Blocked as e:
            log.warning("LinkedIn stopped serving posts (%s)", e)
            break
        if post:
            with_related += bool(post.related)
            crawl.add_related(post)
            if not post.related:
                crawl.read_later(url)
        if pages % 50 == 0:
            log.info("crawl: %d posts read, %d brands so far, %d queued", pages, len(out.brands), len(crawl.heap))
    log.info("crawl: %d LinkedIn posts read, %d of them showed related posts; related cards: %s",
             pages, with_related, dict(crawl.cards.most_common()))
    if save_state:
        crawl.save(config.STATE_FILE)
        log.info("crawl: %d unread posts kept for the next run, %d to re-read when old enough",
                 min(len(crawl.heap), config.QUEUE_KEEP), len(crawl.later))


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


def explain_old_row(r: dict) -> tuple[str, str]:
    """(Signal, Why Added) for a brand row written before those columns existed."""
    src, when, what = r.get("Source", ""), r.get("Posted On", ""), r.get("Looking For", "")
    if src.startswith("LinkedIn job"):
        place = src[src.find("(") + 1:-1] if "(" in src else ""
        return SIGNAL_INFLUENCER_JOB, (f"Hiring a {what.removeprefix('Hiring: ')}{' in ' + place if place else ''} "
                                       f"(job posted {when}): building influencer/creator marketing.")
    if src.startswith("News"):
        return SIGNAL_ASK, f"{src} on {when}: \"{r.get('Matched Text', '')}\"."
    if src.startswith("Reddit"):
        return SIGNAL_ASK, f"Asked on {src} on {when} for {what.lower()}: \"{r.get('Matched Text', '')}\"."
    return SIGNAL_ASK, f"Posted on LinkedIn on {when} asking for {what.lower()}: \"{r.get('Matched Text', '')}\"."


def backfill(tab, rows: list[dict]):
    updates = []
    for r in rows:
        if not r.get("Signal") and r.get("Post / Job URL"):
            signal, why = explain_old_row(r)
            updates += [(r["_row"], "Signal", signal), (r["_row"], "Why Added", why)]
    if updates:
        tab.set_cells(updates)
        log.info("filled Signal / Why Added for %d earlier brand rows", len(updates) // 2)


def sheet_check(brands: list[dict], agencies: list[dict], creators: list[dict]):
    """Log the sheet's size and any duplicates already in it (should always be 0)."""
    keys = Counter(url_key(r.get("Post / Job URL", "")) for r in brands if r.get("Post / Job URL"))
    people = Counter(r.get("Profile", "").lower().rstrip("/") for r in agencies + creators if r.get("Profile"))
    dup_brands = {k: n for k, n in keys.items() if n > 1}
    dup_people = {k: n for k, n in people.items() if n > 1}
    log.info("sheet check: %d brands, %d agencies, %d creators; duplicate brand links: %d, duplicate people: %d%s",
             len(brands), len(agencies), len(creators), len(dup_brands), len(dup_people),
             f" e.g. {list(dup_brands.items())[:3] + list(dup_people.items())[:3]}" if dup_brands or dup_people else "")


def run(dry_run: bool) -> int:
    started = time.time()
    now = datetime.now(timezone.utc)
    book = None
    if dry_run:
        out = Collector([], [], [])
    else:
        from .sheets import Book
        book = Book()
        brands, agencies, creators = book.brands.rows(), book.agencies.rows(), book.creators.rows()
        sheet_check(brands, agencies, creators)
        _safely(backfill, book.brands, brands)
        out = Collector(brands, agencies, creators, book.removed.rows())
    fetcher, searcher, reddit = Fetcher(), Searcher(), Reddit()
    slot = int(time.time() // (3 * 3600))
    try:
        # Brands that say so in a post first; job listings fill up the rest of the target.
        search_and_read(fetcher, searcher, reddit, out, now, slot, save_state=not dry_run)
        for marketing in (False, True):  # influencer/creator job ads, then marketing job ads to fill up
            try:
                collect_jobs(fetcher, out, now, marketing=marketing)
            except Blocked as e:
                log.warning("LinkedIn refused job searches (%s)", e)
                break
    finally:  # whatever happened, keep what was found
        log.info("new: %d brands (target %d%s), %d agencies, %d creators; skipped: %s", len(out.brands),
                 config.TARGET_BRANDS, "" if len(out.brands) >= config.TARGET_BRANDS
                 else f", short by {config.TARGET_BRANDS - len(out.brands)}",
                 len(out.agencies), len(out.creators), dict(out.skipped.most_common()))
        log.info("brands by source: %s", dict(Counter(r["Source"].split(" (")[0] for r in out.brands)))
        log.info("brands by signal: %s", dict(Counter(r.get("Signal", "") for r in out.brands)))
        for r in out.brands:
            if not r["Source"].startswith("LinkedIn job"):
                log.info("  + %s | %s | %s | %s", r.get("Brand / Company") or r.get("Posted By", ""),
                         r["Looking For"], r["Market"], r["Post / Job URL"])
        for kind, rows in (("agency", out.agencies), ("creator", out.creators)):
            for r in rows:
                log.info("  + %s %s | %s | %s", kind, r["Name"], r.get("Headline", "")[:60], r["Profile"])
        if dry_run:
            for tab, rows in (("BRAND", out.brands), ("AGENCY", out.agencies), ("CREATOR", out.creators)):
                for r in rows:
                    print(tab, {k: v for k, v in r.items() if v not in ("", 0)})
        else:
            book.brands.append(out.brands)
            _safely(book.brands.sort_rows, ("Priority", "asc"), ("Added At (IST)", "des"))
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
