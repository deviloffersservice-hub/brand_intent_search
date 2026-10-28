"""Whole-run tests with fake LinkedIn, search engines and Reddit: nothing touches the network."""
from datetime import datetime, timedelta, timezone

import pytest

from brand_intent import config, run
from brand_intent.linkedin import Blocked, Comment, Job, NotFound, Person, Post, parse_jobs, parse_post
from brand_intent.search import Hit

NOW = datetime.now(timezone.utc)


def aid(days_ago: float) -> int:
    return int((NOW - timedelta(days=days_ago)).timestamp() * 1000) << 22


def post_url(slug: str, days_ago: float = 1) -> str:
    return f"https://www.linkedin.com/posts/{slug}_x-activity-{aid(days_ago)}-ab"


class FakeFetcher:
    def __init__(self, posts=None, jobs=None, block_after=None, broken=()):
        self.posts = posts or {}
        self.jobs_by_page = jobs or {}
        self.block_after = block_after
        self.broken = set(broken)
        self.fetched = []

    def post(self, url):
        self.fetched.append(url)
        if self.block_after is not None and len(self.fetched) > self.block_after:
            raise Blocked("999")
        if url in self.broken:
            raise ValueError("unexpected page shape")
        if url not in self.posts:
            raise NotFound("404")
        return self.posts[url]

    def jobs(self, kw, loc, start=0):
        return self.jobs_by_page.get((kw, loc, start), [])


class FakeSearcher:
    def __init__(self, text_hits=None, news_hits=None):
        self.text_hits = text_hits or {}
        self.news_hits = news_hits or {}
        self.asked = self.answered = 0
        self.queries = []

    @property
    def alive(self):
        return True

    def text(self, q, timelimit="w", max_results=25):
        self.asked += 1
        self.queries.append(q)
        return self.text_hits.get(q, [])

    def news(self, q, timelimit="w", max_results=25):
        self.asked += 1
        self.queries.append(q)
        return self.news_hits.get(q, [])


class FakeReddit:
    def thread(self, url, title, snippet):
        return None


def brand_post(url, text="We are looking for an influencer marketing agency for our launch.", country="in"):
    return Post(url=url, author=Person("Acme", "https://www.linkedin.com/company/acme", "company", country),
                published=NOW - timedelta(days=1), text=text,
                comments=[Comment(Person("Aman", "https://www.linkedin.com/in/aman", "in", "in", "Content Creator"),
                                  "Interested!")])


def plan_query(monkeypatch, query="q"):
    """Make every search run use a single LinkedIn query, so tests control the hits."""
    from brand_intent import queries
    monkeypatch.setattr(queries, "LINKEDIN_POSTS", [query])
    monkeypatch.setattr(queries, "REDDIT", [])
    monkeypatch.setattr(queries, "NEWS", [])
    return f"site:linkedin.com/posts {query}"


def test_full_search_path_adds_brand_and_creator(monkeypatch):
    q = plan_query(monkeypatch)
    url = post_url("acme")
    fetcher = FakeFetcher(posts={url: brand_post(url)})
    searcher = FakeSearcher(text_hits={q: [Hit(url + "?utm=x", "t", "s")]})
    out = run.Collector([], [], [])
    run.search_and_read(fetcher, searcher, FakeReddit(), out, NOW, slot=0)
    assert [b["Brand / Company"] for b in out.brands] == ["Acme"]
    assert [c["Name"] for c in out.creators] == ["Aman"]


def test_old_posts_are_skipped_without_fetching(monkeypatch):
    q = plan_query(monkeypatch)
    old = post_url("acme", days_ago=30)
    fetcher = FakeFetcher(posts={old: brand_post(old)})
    out = run.Collector([], [], [])
    run.search_and_read(fetcher, FakeSearcher(text_hits={q: [Hit(old, "", "")]}), FakeReddit(), out, NOW, 0)
    assert fetcher.fetched == [] and out.brands == []


def test_a_broken_page_or_a_block_does_not_lose_earlier_finds(monkeypatch):
    q = plan_query(monkeypatch)
    urls = [post_url(f"brand{i}", days_ago=1 + i / 10) for i in range(4)]
    posts = {u: brand_post(u) for u in urls}
    fetcher = FakeFetcher(posts=posts, broken={urls[1]}, block_after=3)
    out = run.Collector([], [], [])
    run.search_and_read(fetcher, FakeSearcher(text_hits={q: [Hit(u, "", "") for u in urls]}), FakeReddit(), out, NOW, 0)
    assert len(out.brands) == 2  # urls[0] and urls[2]; urls[1] broken; blocked on urls[3]
    assert len(fetcher.fetched) == 4  # nothing fetched after the block


def test_run_stops_at_the_target(monkeypatch):
    q = plan_query(monkeypatch)
    monkeypatch.setattr(config, "TARGET_BRANDS", 2)
    urls = [post_url(f"brand{i}", days_ago=1 + i / 10) for i in range(5)]
    fetcher = FakeFetcher(posts={u: brand_post(u) for u in urls},
                          jobs={("influencer marketing", "India", 0): [Job("https://www.linkedin.com/jobs/view/1", "Influencer Marketing Manager", "Nykaa", "https://www.linkedin.com/company/nykaa", "Mumbai, India", NOW)]})
    out = run.Collector([], [], [])
    run.search_and_read(fetcher, FakeSearcher(text_hits={q: [Hit(u, "", "") for u in urls]}), FakeReddit(), out, NOW, 0)
    run.collect_jobs(fetcher, out, NOW)
    # all hits of one query are read, but no further searches or job pages once the target is met
    assert len(out.brands) >= 2 and not any(b["Source"].startswith("LinkedIn job") for b in out.brands)


def test_jobs_fill_up_skip_agencies_old_and_repeat_companies():
    jobs = [
        Job("https://www.linkedin.com/jobs/view/1", "Influencer Marketing Manager", "Nykaa",
            "https://www.linkedin.com/company/nykaa", "Mumbai, Maharashtra, India", NOW - timedelta(days=2)),
        Job("https://www.linkedin.com/jobs/view/2", "Influencer Marketing Executive", "Nykaa",
            "https://www.linkedin.com/company/nykaa", "Mumbai, Maharashtra, India", NOW - timedelta(days=2)),
        Job("https://www.linkedin.com/jobs/view/3", "Manager - Influencer Marketing", "dentsu",
            "https://www.linkedin.com/company/dentsu", "Gurugram, India", NOW),
        Job("https://www.linkedin.com/jobs/view/4", "Influencer Marketing Lead", "Old Co",
            "https://www.linkedin.com/company/oldco", "Pune, India", NOW - timedelta(days=30)),
        Job("https://www.linkedin.com/jobs/view/5", "Software Engineer", "Zepto",
            "https://www.linkedin.com/company/zepto", "Bengaluru, India", NOW),
        Job("https://www.linkedin.com/jobs/view/6", "Influencer Marketing Manager", "Glossier",
            "https://www.linkedin.com/company/glossier", "New York, NY", NOW),
        Job("https://www.linkedin.com/jobs/view/7", "Influencer Marketing Manager", "Zalando",
            "https://www.linkedin.com/company/zalando", "Berlin, Germany", NOW),
    ]
    out = run.Collector([], [], [])
    run.collect_jobs(FakeFetcher(jobs={("influencer marketing", "India", 0): jobs}), out, NOW)
    assert [(b["Brand / Company"], b["Market"]) for b in out.brands] == [("Nykaa", "India"), ("Glossier", "US")]


def test_companies_already_in_sheet_from_jobs_are_not_added_again():
    out = run.Collector([{"Brand / Company": "Nykaa", "Source": "LinkedIn job (Mumbai)", "Post / Job URL": "x"}], [], [])
    job = Job("https://www.linkedin.com/jobs/view/9", "Influencer Marketing Manager", "Nykaa",
              "https://www.linkedin.com/company/nykaa", "Mumbai, India", NOW)
    run.collect_jobs(FakeFetcher(jobs={("influencer marketing", "India", 0): [job]}), out, NOW)
    assert out.brands == []


def test_news_and_reddit_rows(monkeypatch):
    out = run.Collector([], [], [])
    run.handle_news(Hit("https://news/1", "Mamaearth calls for digital creative pitch", "Mumbai-based brand",
                        NOW - timedelta(days=2), "afaqs"), out, NOW)
    run.handle_news(Hit("https://news/2", "Old brand calls for pitch in India", "", NOW - timedelta(days=40)), out, NOW)
    run.handle_news(Hit("https://news/3", "Acme GmbH calls for agency pitch", "Berlin", NOW), out, NOW)
    assert [b["Brand / Company"] for b in out.brands] == ["Mamaearth"]

    from brand_intent.reddit import Thread

    class R:
        def thread(self, url, title, snippet):
            return Thread(url="https://www.reddit.com/r/IndianStartups/comments/abc/", subreddit="IndianStartups",
                          title="Looking for an influencer marketing agency for our D2C brand", text="",
                          author="founder1", published=NOW - timedelta(days=1), full=True,
                          comments=[("agencyguy", "Our agency has run 50 creator campaigns, DM me"),
                                    ("rando", "following")])
    run.handle_reddit(R(), Hit("https://www.reddit.com/r/IndianStartups/comments/abc/x", "", ""), out, NOW)
    reddit_rows = [b for b in out.brands if b["Source"].startswith("Reddit")]
    assert len(reddit_rows) == 1 and reddit_rows[0]["Market"] == "India" and reddit_rows[0]["Agencies in Comments"] == 1
    assert out.agencies[0]["Name"] == "u/agencyguy"


def test_parsers_survive_garbage():
    p = parse_post("<html>nothing here</html>", post_url("x"))
    assert p.author.name == "" and p.comments == [] and p.published is not None  # date from the link
    assert parse_jobs("") == [] and parse_jobs("<li>broken</li>") == []


@pytest.mark.parametrize("text", ["", "   ", "🔥🔥🔥", "a" * 20000])
def test_intent_handles_odd_text(text):
    from brand_intent import intent
    assert intent.wants(text) == []
    assert intent.market("", text) == ""


def test_related_cards_are_parsed_and_queued_best_first():
    from brand_intent.linkedin import parse_related

    def card(slug, text, days_ago, sub="www"):
        a = aid(days_ago)
        return (f'<li class="mb-1.5"><a href="https://{sub}.linkedin.com/in/{slug}?trk=x" aria-label="Post by {slug}">'
                f'</a><a href="https://www.linkedin.com/posts/{slug}_x-activity-{a}-ab?trk=y">p</a>'
                f'<div data-activity-urn="urn:li:activity:{a}"></div>'
                f'<p class="attributed-text-segment-list__content">{text}</p></li>')
    page = ('<section class="related-posts">'
            + card("asker", "We are looking for an influencer marketing agency for Q1", 2, "in")
            + card("topical", "5 lessons from our influencer campaign", 3)
            + card("offtopic", "Happy Diwali to everyone!", 1)
            + card("old", "Looking for UGC creators", 40) + "</section>")
    rel = parse_related(page)
    assert [r.author.name for r in rel] == ["asker", "topical", "offtopic", "old"]
    assert rel[0].author.country == "in" and rel[0].text.startswith("We are looking")
    crawl = run.Crawl(NOW)
    crawl.add_related(Post(url="u", author=Person(""), published=NOW, text="", related=rel))
    order = [crawl.pop() for _ in range(len(crawl.heap))]
    assert [u.split("/posts/")[1].split("_")[0] for u in order] == ["asker", "topical"]


def test_crawl_follows_related_posts_to_a_brand_ask(monkeypatch):
    from brand_intent.linkedin import Related
    q = "site:linkedin.com/posts q"
    from brand_intent import queries
    monkeypatch.setattr(queries, "LINKEDIN_POSTS", [])
    monkeypatch.setattr(queries, "LINKEDIN_SEEDS", ["q"])
    monkeypatch.setattr(queries, "REDDIT", [])
    monkeypatch.setattr(queries, "NEWS", [])
    seed, ask = post_url("seed"), post_url("brandx", 0.5)
    seed_post = Post(url=seed, author=Person("Agency", "https://www.linkedin.com/company/agency", "company", "www"),
                     published=NOW, text="Our influencer campaign results",
                     related=[Related(ask, Person("Brand X"), "Looking for an influencer marketing agency", NOW)])
    fetcher = FakeFetcher(posts={seed: seed_post, ask: brand_post(ask)})
    out = run.Collector([], [], [])
    run.search_and_read(fetcher, FakeSearcher(text_hits={q: [Hit(seed, "", "")]}), FakeReddit(), out, NOW, 0)
    assert fetcher.fetched == [seed, ask]
    assert out.brands[0]["Source"] == "LinkedIn post (related posts)"
