"""Reddit threads found by web search. Reddit's public JSON is tried for the full post and its
comments; it often refuses cloud servers, and then only the search title and snippet are used."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

THREAD_RE = re.compile(r"https?://(?:www\.|old\.)?reddit\.com/r/([^/]+)/comments/([a-z0-9]+)", re.I)


@dataclass
class Thread:
    url: str
    subreddit: str
    title: str
    text: str
    author: str = ""
    published: datetime | None = None
    comments: list[tuple[str, str]] = field(default_factory=list)  # (username, text)
    full: bool = False  # False: built from the search snippet only


def thread_url(url: str) -> tuple[str, str, str] | None:
    """-> (canonical url, subreddit, id) or None if it isn't a thread link."""
    m = THREAD_RE.search(url or "")
    if not m:
        return None
    return f"https://www.reddit.com/r/{m.group(1)}/comments/{m.group(2)}/", m.group(1), m.group(2)


def parse_thread_json(data: list, url: str, subreddit: str) -> Thread:
    post = data[0]["data"]["children"][0]["data"]
    comments = []
    for c in data[1]["data"]["children"] if len(data) > 1 else []:
        d = c.get("data", {})
        if c.get("kind") == "t1" and d.get("author") not in (None, "[deleted]", "AutoModerator"):
            comments.append((d["author"], d.get("body", "")[:1000]))
    return Thread(url=url, subreddit=subreddit, title=post.get("title", ""), text=post.get("selftext", ""),
                  author=post.get("author", ""), full=True,
                  published=datetime.fromtimestamp(post["created_utc"], tz=timezone.utc) if post.get("created_utc") else None,
                  comments=comments)


class Reddit:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "brand-intent-search/1.0 (public research script)"
        self.refused = False

    def thread(self, url: str, title: str, snippet: str) -> Thread | None:
        parts = thread_url(url)
        if not parts:
            return None
        canon, sub, tid = parts
        if not self.refused:
            try:
                r = self.session.get(f"https://www.reddit.com/comments/{tid}.json?limit=50", timeout=20)
                if r.status_code == 200:
                    return parse_thread_json(r.json(), canon, sub)
                if r.status_code in (403, 429):
                    log.info("reddit refused (%s); using search snippets for the rest of this run", r.status_code)
                    self.refused = True
            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                log.info("reddit %s: %s", tid, str(e)[:80])
        return Thread(url=canon, subreddit=sub, title=title, text=snippet)
