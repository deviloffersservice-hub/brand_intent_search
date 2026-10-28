"""Logged-out LinkedIn: public post pages (author, date, text, comments) and public job listings."""
from __future__ import annotations

import html as htmllib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

from . import config

log = logging.getLogger(__name__)

# The same browser identities the creator pipeline has used for weeks without trouble.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]
POST_URL_RE = re.compile(r"https://(?:[a-z]{2,3}\.)?linkedin\.com/posts/[^\"'\s?#<>]+")
ACTOR_RE = re.compile(r"https://([a-z]{2,3})\.linkedin\.com/(in|company|school|showcase)/([^\"'?&/#\s<]+)")


class Blocked(Exception):
    """LinkedIn refused several requests in a row; stop for this run."""


class NotFound(Exception):
    pass


def activity_time(activity_id: str | int | None) -> datetime | None:
    """LinkedIn activity ids carry their creation time: the top 41 bits are epoch milliseconds."""
    try:
        return datetime.fromtimestamp((int(activity_id) >> 22) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def activity_id_from_url(url: str) -> str | None:
    m = re.search(r"activity[-:](\d{15,})", url)
    return m.group(1) if m else None


def canonical_post_url(url: str) -> str:
    url = htmllib.unescape(url).split("?")[0].split("#")[0]
    return re.sub(r"^https://(?:[a-z]{2,3}\.)?linkedin\.com", "https://www.linkedin.com", url)


def country_name(subdomain: str) -> str:
    return {"www": "US", "in": "India"}.get(subdomain, subdomain.upper() if subdomain else "")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


@dataclass
class Person:
    """A post author or commenter: a person or a company page."""
    name: str
    url: str = ""  # profile or company page, www form
    kind: str = ""  # "in" (person) or "company"
    country: str = ""  # LinkedIn subdomain: "www" (US), "in" (India), "uk", ...
    headline: str = ""

    @property
    def is_company(self) -> bool:
        return self.kind in ("company", "showcase", "school")


def person_from_link(url: str, name: str = "", headline: str = "") -> Person:
    m = ACTOR_RE.search(url or "")
    if not m:
        return Person(name=name, headline=headline)
    sub, kind, slug = m.groups()
    return Person(name=name, url=f"https://www.linkedin.com/{kind}/{slug}", kind=kind, country=sub, headline=headline)


@dataclass
class Comment:
    author: Person
    text: str


@dataclass
class Post:
    url: str
    author: Person
    published: datetime | None
    text: str
    comments: list[Comment] = field(default_factory=list)
    related: list = field(default_factory=list)  # Related cards; filled by parse_post


def parse_post(page: str, url: str) -> Post:
    data = {}
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if d.get("@type") in ("SocialMediaPosting", "DiscussionForumPosting", "Article"):
            data = d
            break
    published = None
    if data.get("datePublished"):
        try:
            published = datetime.fromisoformat(data["datePublished"].replace("Z", "+00:00"))
        except ValueError:
            pass
    published = published or activity_time(activity_id_from_url(url))
    text = data.get("articleBody") or data.get("text") or data.get("headline") or ""
    if not text:
        body = re.search(r'data-test-id="main-feed-activity-card__commentary"[^>]*>(.*?)</p>', page, re.S)
        text = _text(body.group(1)) if body else ""

    # Post author: the actor link at the top of the post, then the headline line under it.
    author = Person(name=(data.get("author") or {}).get("name", ""))
    actor = re.search(r'<a[^>]+href="([^"]+)"[^>]*data-tracking-control-name="public_post_feed-actor-name"[^>]*>(.*?)</a>',
                      page, re.S)
    if actor:
        author = person_from_link(actor.group(1), _text(actor.group(2)) or author.name)
        # The headline is the short grey line right under the name, inside the post header; never
        # the post text (which comes later and is long).
        after = page[actor.end(): actor.end() + 2500]
        after = after.split("main-feed-activity-card__commentary")[0].split("attributed-text-segment-list")[0]
        line = re.search(r'<p class="[^"]*text-color-text-low-emphasis[^"]*"[^>]*>(.*?)</p>', after, re.S)
        headline = _text(line.group(1)) if line else ""
        author.headline = headline if len(headline) <= 220 else ""

    comments = []
    for chunk in re.split(r'<section class="comment', page)[1:]:
        link = re.search(r'class="[^"]*comment__author[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, re.S) or \
            re.search(r'href="([^"]+)"[^>]*class="[^"]*comment__author[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
        if not link:
            continue
        headline = re.search(r'comment__author-headline[^>]*>(.*?)</', chunk, re.S)
        body = re.search(r'comment__text[^>]*>(.*?)</(?:p|div|span)>', chunk, re.S) or \
            re.search(r'class="[^"]*comment__body[^"]*"[^>]*>(.*)', chunk, re.S)
        person = person_from_link(link.group(1), _text(link.group(2)), _text(headline.group(1)) if headline else "")
        comments.append(Comment(person, _text(body.group(1))[:1000] if body else ""))
    return Post(url=canonical_post_url(url), author=author, published=published, text=text, comments=comments,
                related=parse_related(page))


@dataclass
class Job:
    url: str
    title: str
    company: str
    company_url: str
    location: str
    posted: datetime | None


def parse_jobs(page: str) -> list[Job]:
    jobs = []
    for card in re.split(r'<li[ >]', page)[1:]:
        link = re.search(r'href="(https://[a-z]{2,3}\.linkedin\.com/jobs/view/[^"?]+)', card)
        title = re.search(r'class="base-search-card__title"[^>]*>(.*?)</h3>', card, re.S)
        if not link or not title:
            continue
        company = re.search(r'class="base-search-card__subtitle"[^>]*>(.*?)</h4>', card, re.S)
        company_link = re.search(r'href="(https://[a-z]{2,3}\.linkedin\.com/company/[^"?]+)', card)
        location = re.search(r'class="job-search-card__location"[^>]*>(.*?)</span>', card, re.S)
        when = re.search(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})"', card)
        posted = datetime.strptime(when.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc) if when else None
        jobs.append(Job(url=re.sub(r"^https://[a-z]{2,3}\.", "https://www.", link.group(1)), title=_text(title.group(1)),
                        company=_text(company.group(1)) if company else "",
                        company_url=re.sub(r"^https://[a-z]{2,3}\.", "https://www.", company_link.group(1))
                        if company_link else "",
                        location=_text(location.group(1)) if location else "", posted=posted))
    return jobs


class Fetcher:
    """Polite logged-out fetcher. Raises Blocked after several refusals in a row."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": random.choice(USER_AGENTS),
                                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                     "Accept-Language": "en-US,en;q=0.9"})
        self.blocks = 0
        self.requests = 0
        self._last = 0.0

    def get(self, url: str) -> str:
        wait = random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX) - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        try:
            r = self.session.get(url, timeout=25, allow_redirects=True)
        except requests.RequestException as e:
            raise NotFound(str(e)) from e
        if r.status_code in (429, 999) or "/authwall" in r.url:
            self.blocks += 1
            if self.blocks >= config.MAX_CONSECUTIVE_BLOCKS:
                raise Blocked(f"{r.status_code} on {url}")
            time.sleep(10 * self.blocks)
            raise NotFound(f"refused ({r.status_code})")
        if r.status_code != 200 or re.search(r"/(login|signup|uas)/", r.url):
            raise NotFound(f"{r.status_code}")
        self.blocks = 0
        return r.text

    def post(self, url: str) -> Post:
        return parse_post(self.get(canonical_post_url(url)), url)

    def jobs(self, keywords: str, location: str, start: int = 0) -> list[Job]:
        seconds = config.MAX_AGE_DAYS * 86400
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
               f"keywords={quote_plus(keywords)}&location={quote_plus(location)}&f_TPR=r{seconds}&start={start}")
        return parse_jobs(self.get(url))


@dataclass
class Related:
    """A card in a post page's "More Relevant Posts" section: enough to judge it without a fetch."""
    url: str
    author: Person
    text: str
    published: datetime | None


def parse_related(page: str) -> list[Related]:
    start = page.find("related-posts")
    if start < 0:
        return []
    out = []
    for chunk in re.split(r'<li class="mb-1\.5">', page[start:])[1:]:
        post = POST_URL_RE.search(chunk)
        if not post:
            continue
        url = canonical_post_url(post.group(0))
        urn = re.search(r'data-activity-urn="urn:li:activity:(\d+)"', chunk)
        actor = ACTOR_RE.search(chunk)
        name = re.search(r'aria-label="Post by ([^"]+)"', chunk)
        body = re.search(r'attributed-text-segment-list__content[^>]*>(.*?)</p>', chunk, re.S)
        author = person_from_link(actor.group(0) if actor else "", htmllib.unescape(name.group(1)) if name else "")
        out.append(Related(url=url, author=author, text=_text(body.group(1)) if body else "",
                           published=activity_time(urn.group(1) if urn else activity_id_from_url(url))))
    return out
