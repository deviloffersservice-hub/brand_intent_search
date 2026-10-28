"""Diagnostics: which search styles get answers from GitHub's machines, and what the job filter drops.

    python -m brand_intent.probe
"""
from __future__ import annotations

import logging
import time

from . import intent, queries
from .linkedin import Fetcher

log = logging.getLogger("probe")

VARIANTS = [
    ("text", "site:linkedin.com/posts looking for influencer marketing agency", "w"),
    ("text", "site:linkedin.com/posts looking for influencer marketing agency", "m"),
    ("text", 'site:linkedin.com/posts "looking for an influencer marketing agency"', "m"),
    ("text", 'site:linkedin.com/posts "influencer marketing agency"', "w"),
    ("text", "site:linkedin.com/posts looking for influencers brand collaboration", "w"),
    ("text", "site:linkedin.com/posts looking for creators collaboration", "w"),
    ("text", "linkedin.com/posts looking for influencer marketing agency", "w"),
    ("text", "linkedin post looking for influencer marketing agency India", "w"),
    ("text", "site:linkedin.com/posts hiring influencer marketing agency India", "m"),
    ("text", "site:linkedin.com/posts healthcare", "w"),  # known to work in the creator project
    ("text", "site:reddit.com influencer marketing agency recommend", "w"),
    ("text", "site:reddit.com looking for influencer marketing agency", "m"),
    ("news", "agency pitch influencer marketing", "w"),
    ("news", "calls for agency pitch", "w"),
    ("news", "digital mandate agency India", "w"),
]


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from ddgs import DDGS
    for noisy in ("primp", "ddgs", "httpx"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    for kind, q, tl in VARIANTS:
        for backend in (["auto", "duckduckgo", "brave", "yahoo", "mojeek"] if kind == "text" else ["auto"]):
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
