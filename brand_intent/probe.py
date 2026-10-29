"""Diagnostics: which search styles get answers from GitHub's machines, and what the job filter drops.

    python -m brand_intent.probe
"""
from __future__ import annotations

import logging
import sys
import time

from . import intent, queries
from .linkedin import Fetcher

log = logging.getLogger("probe")

VARIANTS = [(kind, q, tl) for q in [
    'site:linkedin.com/posts "urgent requirement" linkedin creators',
    'site:linkedin.com/posts "urgent requirement" influencer marketing',
    'site:linkedin.com/posts "looking for vendors" creators',
    'site:linkedin.com/posts #hiringlinkedinvendors',
    'site:linkedin.com/posts "connect us with" linkedin creators',
    'site:linkedin.com/posts "looking for linkedin creators"',
] for kind, tl in (("text", None), ("text", "m"), ("text", "w"))]


def related_check():
    """Why do some runs' seed posts show no related posts? Look at each seed page."""
    import re
    from datetime import datetime, timezone
    from .linkedin import POST_URL_RE, activity_id_from_url, activity_time, canonical_post_url, parse_post
    from .search import Searcher
    s, f = Searcher(), Fetcher()
    urls = []
    for q in ["influencer marketing", "creator marketing", "LinkedIn creators", "marketing"]:
        urls += [canonical_post_url(m.group(0)) for h in s.text(f"site:linkedin.com/posts {q}", timelimit="w")
                 if (m := POST_URL_RE.search(h.url))]
    now = datetime.now(timezone.utc)
    for url in list(dict.fromkeys(urls))[:16]:
        try:
            html = f.get(url)
        except Exception as e:
            log.info("probe related %s: %s", url, e)
            continue
        p = parse_post(html, url)
        aid = activity_id_from_url(url)
        age = (now - activity_time(aid)).days if aid else None
        others = len(set(POST_URL_RE.findall(html)) - {url})
        marks = [m for m in ("related-posts", "More Relevant Posts", "more-from", "show-more-less", "authwall",
                             "public_post_feed-actor-name") if m in html]
        log.info("probe related | %s | kind=%s age=%sd len=%d related=%d other_post_links=%d marks=%s",
                 url.split("/posts/")[1][:50], p.author.kind, age, len(html), len(p.related), others, marks)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if "--related" in sys.argv:
        related_check()
    from ddgs import DDGS
    for noisy in ("primp", "ddgs", "httpx"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    for kind, q, tl in VARIANTS:
        for backend in (["yahoo", "auto", "duckduckgo", "brave"] if kind == "text" else ["auto"]):
            try:
                if kind == "text":
                    rows = DDGS().text(q, region="wt-wt", timelimit=tl, max_results=25, backend=backend)
                else:
                    rows = DDGS().news(q, region="wt-wt", timelimit=tl, max_results=25)
                urls = [r.get("href") or r.get("url") for r in rows]
                li = sum(1 for u in urls if u and ("linkedin.com/posts" in u or "reddit.com" in u))
                log.info("probe %-5s %-4s %-10s %3d results (%d linkedin/reddit) | %s | e.g. %s", kind, tl, backend,
                         len(rows), li, q, (rows[0].get("title", "") if rows else "")[:60])
            except Exception as e:
                log.info("probe %-5s %-4s %-10s fail %s | %s", kind, tl, backend, str(e)[:50], q)
            time.sleep(4)

    # What the job filter calls an agency/recruiter (to check it isn't dropping real brands).
    f = Fetcher()
    dropped, kept = set(), set()
    for kw in queries.JOB_KEYWORDS[:2]:
        for loc in queries.JOB_LOCATIONS:
            for job in f.jobs(kw, loc):
                slug = job.company_url.rsplit("/", 1)[-1].replace("-", " ")
                (dropped if intent.looks_like_agency(job.company, slug=slug) else kept).add(job.company)
    log.info("probe jobs dropped as agency/recruiter: %s", sorted(dropped))
    log.info("probe jobs kept as brands: %s", sorted(kept))


if __name__ == "__main__":
    main()
