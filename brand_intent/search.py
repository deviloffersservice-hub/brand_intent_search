"""Free web search through ddgs (several engines), paced so engines answer more queries."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from . import config

log = logging.getLogger(__name__)

# Order from a diagnostics run on GitHub's machines: yahoo and "auto" (ddgs picks an engine) answered
# site:linkedin.com searches; the others rarely did.
BACKENDS = ["yahoo", "auto", "duckduckgo", "brave", "startpage", "mojeek"]


@dataclass
class Hit:
    url: str
    title: str
    snippet: str
    published: datetime | None = None  # only news results carry a date
    source: str = ""


class Searcher:
    """One query at a time with a gap between queries. A query no engine answers is often just a
    phrase with no recent results, so it doesn't count against the engines by itself. From the third
    unanswered query in a row, each one counts as a failure for every engine, and an engine is dropped
    after ENGINE_MAX_FAILS failures; searching stops when no engine is left or the budget is spent."""

    ENGINE_MAX_FAILS = 4

    def __init__(self):
        self.fails = {b: 0 for b in BACKENDS}
        self.dead_in_a_row = 0
        self.asked = self.answered = 0
        self._last = 0.0
        try:
            from ddgs import DDGS
            self._ddgs = DDGS
        except ImportError:
            self._ddgs = None
            self.fails = {}
        for noisy in ("primp", "ddgs", "httpx"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    @property
    def alive(self) -> bool:
        return bool(self.fails) and self.asked < config.SEARCHES_PER_RUN

    def _pace(self):
        wait = config.SEARCH_GAP_SECONDS - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def text(self, query: str, timelimit: str = "w", max_results: int = 25) -> list[Hit]:
        return self._run(query, lambda d, b: d.text(query, region="wt-wt", timelimit=timelimit,
                                                     max_results=max_results, backend=b), news=False)

    def news(self, query: str, timelimit: str = "w", max_results: int = 25) -> list[Hit]:
        # News only has a few engines; "auto" picks among them.
        return self._run(query, lambda d, b: d.news(query, region="wt-wt", timelimit=timelimit,
                                                     max_results=max_results), news=True, backends=["auto"])

    def _run(self, query, call, news: bool, backends=None) -> list[Hit]:
        if not self.alive:
            return []
        self._pace()
        self.asked += 1
        failed = []
        for backend in backends or list(self.fails):
            try:
                rows = call(self._ddgs(), backend)
            except Exception as e:  # blocked, captcha, timeout or no results
                rows = []
                log.debug("search %r on %s: %s", query, backend, str(e)[:80])
            hits = [self._hit(r, news) for r in rows]
            hits = [h for h in hits if h.url]
            if hits:
                for b in failed:
                    self._failed(b)
                if backend in self.fails:
                    self.fails[backend] = 0
                self.dead_in_a_row = 0
                self.answered += 1
                log.info("search %r on %s -> %d results", query, backend, len(hits))
                return hits
            failed.append(backend)
            time.sleep(2)
        self.dead_in_a_row += 1
        if self.dead_in_a_row >= 3:
            for b in failed:
                self._failed(b)
        log.info("search %r: no results", query)
        return []

    @staticmethod
    def _hit(r: dict, news: bool) -> Hit:
        published = None
        if news and r.get("date"):
            try:
                published = datetime.fromisoformat(str(r["date"]).replace("Z", "+00:00"))
            except ValueError:
                pass
        return Hit(url=r.get("url") if news else r.get("href", ""), title=r.get("title", ""),
                   snippet=r.get("body", ""), published=published, source=r.get("source", ""))

    def _failed(self, backend: str):
        if backend in self.fails:
            self.fails[backend] += 1
            if self.fails[backend] >= self.ENGINE_MAX_FAILS:
                log.info("dropping search engine %s for this run", backend)
                del self.fails[backend]
