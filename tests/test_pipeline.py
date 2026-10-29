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
    # India only now: the New York and Berlin jobs are skipped; job ads go to the hiring tab
    assert out.brands == [] and [(b["Brand / Company"], b["Market"]) for b in out.jobs] == [("Nykaa", "India")]


def test_companies_already_in_sheet_from_jobs_are_not_added_again():
    out = run.Collector([{"Brand / Company": "Nykaa", "Source": "LinkedIn job (Mumbai)", "Post / Job URL": "x"}], [], [])
    job = Job("https://www.linkedin.com/jobs/view/9", "Influencer Marketing Manager", "Nykaa",
              "https://www.linkedin.com/company/nykaa", "Mumbai, India", NOW)
    run.collect_jobs(FakeFetcher(jobs={("influencer marketing", "India", 0): [job]}), out, NOW)
    assert out.brands == []


def test_news_and_reddit_rows(monkeypatch):
    out = run.Collector([], [], [])
    run.handle_news(Hit("https://news/1", "Mamaearth calls for influencer marketing pitch", "Mumbai-based brand",
                        NOW - timedelta(days=2), "afaqs"), out, NOW)
    run.handle_news(Hit("https://news/4", "Bisleri calls for digital creative pitch", "Mumbai", NOW, "afaqs"), out, NOW)
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


def test_searcher_keeps_going_through_quiet_phrases(monkeypatch):
    from brand_intent import search
    monkeypatch.setattr(search.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "SEARCH_GAP_SECONDS", 0)
    answers = {"good": [{"href": "https://www.linkedin.com/posts/a_x-activity-1-b", "title": "t", "body": "b"}]}

    class FakeDDGS:
        def text(self, query, backend, **kw):
            if query in answers and backend == "yahoo":
                return answers[query]
            raise RuntimeError("No results found.")

    s = search.Searcher()
    s._ddgs = FakeDDGS
    for q in ["quiet1", "quiet2", "quiet3", "good", "quiet4"]:
        s.text(q)
    assert s.alive and s.answered == 1  # three quiet phrases in a row didn't end the searching


def test_same_news_story_from_two_outlets_is_one_row():
    out = run.Collector([], [], [])
    for url, src in (("https://a/1", "Storyboard18"), ("https://b/2", "MediaNews4U")):
        run.handle_news(Hit(url, "Nykaa invites pitches for influencer mandate", "in Mumbai", NOW, src), out, NOW)
    assert len(out.brands) == 1


def test_author_headline_is_never_the_post_text():
    page = ('<a href="https://www.linkedin.com/in/jane?trk=x" data-tracking-control-name="public_post_feed-actor-name">'
            'Jane</a><div></div><p data-test-id="main-feed-activity-card__commentary" class="attributed-text-segment-list__content">'
            + "We are looking for an influencer marketing agency. " * 20 + '</p>')
    p = parse_post(page, post_url("jane"))
    assert p.author.name == "Jane" and p.author.headline == ""


# --- cases from the code review -------------------------------------------------------------------
def test_same_post_written_differently_is_one_row():
    a = aid(1)
    forms = [f"https://www.linkedin.com/posts/mamaearth_%E0%A4%B9-activity-{a}-AbCd",
             f"https://www.linkedin.com/posts/mamaearth_ह-activity-{a}-XyZw/",
             f"https://in.linkedin.com/posts/MAMAEARTH_x-activity-{a}-ab?utm_source=share",
             f"https://www.linkedin.com/feed/update/urn:li:activity:{a}/"]
    assert len({run.url_key(u) for u in forms}) == 1
    out = run.Collector([{"Post / Job URL": forms[0]}], [], [])
    assert out.seen(forms[1]) and out.seen(forms[3])
    assert not out.add_brand({"Post / Job URL": forms[2]})


def test_jobs_and_reddit_keys():
    assert run.url_key("https://www.linkedin.com/jobs/view/influencer-marketing-at-nykaa-4483607308") == \
        run.url_key("https://in.linkedin.com/jobs/view/influencer-marketing-at-nykaa-4483607308/?trk=x")
    assert run.url_key("https://www.reddit.com/r/IndianStartups/comments/AbC123/x") == \
        run.url_key("https://old.reddit.com/r/indianstartups/comments/abc123/")
    out = run.Collector([{"Brand / Company": "Honasa Consumer Ltd", "Source": "LinkedIn job (x)", "Post / Job URL": "a"},
                         {"Brand / Company": "Acme", "Company LinkedIn": "https://www.linkedin.com/company/acme-in",
                          "Source": "LinkedIn job (x)", "Post / Job URL": "b"}], [], [])
    assert out.company_listed("Honasa Consumer Limited", "https://www.linkedin.com/company/honasa")
    assert not out.company_listed("Acme", "https://www.linkedin.com/company/acme-us")
    assert out.company_listed("Acme", "https://www.linkedin.com/company/acme-in")


def test_undated_reddit_snippets_and_news_are_skipped():
    from brand_intent.reddit import Thread
    out = run.Collector([], [], [])

    class R:
        def thread(self, url, title, snippet):
            return Thread(url="https://www.reddit.com/r/IndianStartups/comments/zz/", subreddit="IndianStartups",
                          title="Looking for an influencer marketing agency", text="", published=None)
    run.handle_reddit(R(), Hit("https://www.reddit.com/r/IndianStartups/comments/zz/x", "", ""), out, NOW)
    run.handle_news(Hit("https://news/9", "Bisleri calls for creative pitch in India", "", None), out, NOW)
    assert out.brands == []


def test_indiana_is_not_india():
    from brand_intent.reddit import Thread

    class R:
        def thread(self, url, title, snippet):
            return Thread(url="https://www.reddit.com/r/Indiana/comments/q1/", subreddit="Indiana",
                          title="Looking for influencers for my bakery in Fort Wayne", text="", published=NOW)
    out = run.Collector([], [], [])
    run.handle_reddit(R(), Hit("https://www.reddit.com/r/Indiana/comments/q1/x", "", ""), out, NOW)
    assert out.brands == [] or out.brands[0]["Market"] != "India"


def test_news_about_an_agency_is_not_a_brand():
    out = run.Collector([], [], [])
    run.handle_news(Hit("https://n/1", "WPP India seeks partners for influencer mandate in Bengaluru", "", NOW), out, NOW)
    assert out.brands == []


def test_naive_dates_do_not_crash():
    page = ('<script type="application/ld+json">{"@type": "SocialMediaPosting", "datePublished": "2026-10-27T10:00:00",'
            ' "articleBody": "hello"}</script>')
    p = parse_post(page, post_url("x"))
    assert p.published.tzinfo is not None
    assert run.recent(p.published, NOW) in (True, False)


def test_comment_counts_include_people_already_listed():
    out = run.Collector([], [{"Profile": "https://www.linkedin.com/in/riya"}], [])
    post = Post(url=post_url("acme"), author=Person("Acme", "https://www.linkedin.com/company/acme", "company", "in"),
                published=NOW, text="We are looking for an influencer marketing agency",
                comments=[Comment(Person("Riya", "https://www.linkedin.com/in/riya", "in", "in",
                                         "Founder, Spark Influencer Agency"), "We'd love to help")])
    run.handle_post(FakeFetcher(posts={post.url: post}), post.url, out, NOW, "search")
    assert out.brands[0]["Agencies in Comments"] == 1 and out.agencies == []


def test_sheet_check_reports_duplicates(caplog):
    import logging
    caplog.set_level(logging.INFO)
    a = aid(1)
    run.sheet_check([{"Post / Job URL": f"https://www.linkedin.com/posts/x_y-activity-{a}-ab"},
                     {"Post / Job URL": f"https://in.linkedin.com/posts/x_y-activity-{a}-cd/"}], [], [])
    assert "duplicate brand links: 1" in caplog.text


def test_crawl_queue_survives_between_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_FILE", str(tmp_path / "q.json"))
    c = run.Crawl(NOW)
    c.push(post_url("asker"), 0, "search")
    c.push(post_url("topical", 2), 1)
    c.push(post_url("old", 40), 1)  # too old: never queued
    c.save(config.STATE_FILE)
    later = run.Crawl(NOW)
    later.load(config.STATE_FILE)
    assert len(later.heap) == 2 and later.pop() == post_url("asker")
    assert later.origin[run.url_key(post_url("asker"))] == "search"
    run.Crawl(NOW).load(str(tmp_path / "missing.json"))  # no saved queue yet: fine


def test_young_posts_are_crawled_last_and_reread_when_old_enough(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_FILE", str(tmp_path / "q.json"))
    c = run.Crawl(NOW)
    young, older, ask = post_url("young", 1), post_url("older", 5), post_url("ask", 0.5)
    c.push(young, 2, "search")
    c.push(older, 2, "search")
    c.push(ask, 0)  # asks are read first whatever their age
    assert [c.pop() for _ in range(3)] == [ask, older, young]
    c.read_later(young)  # read at 1 day old: no related posts yet
    c.read_later(older)  # already old enough: nothing to wait for
    assert list(c.later) == [young]
    c.save(config.STATE_FILE)
    # three days later the young post is read again
    later = run.Crawl(NOW + timedelta(days=3))
    later.load(config.STATE_FILE)
    assert later.pop() == young and later.origin[run.url_key(young)] == "related posts"
    # an older save format (a plain list) still loads
    import json
    (tmp_path / "old.json").write_text(json.dumps([[1, older, "search"]]))
    old = run.Crawl(NOW)
    old.load(str(tmp_path / "old.json"))
    assert old.pop() == older


def test_signal_and_why_on_every_kind_of_row():
    out = run.Collector([], [], [])
    # direct ask
    post = brand_post(post_url("acme"))
    run.handle_post(FakeFetcher(posts={post.url: post}), post.url, out, NOW, "search")
    # brand company page announcing a creator campaign
    camp = Post(url=post_url("nykaa", 4), author=Person("Nykaa", "https://www.linkedin.com/company/nykaa", "company", "in"),
                published=NOW - timedelta(days=4), text="We partnered with 200 creators for our festive sale!")
    run.handle_post(FakeFetcher(posts={camp.url: camp}), camp.url, out, NOW, "related posts")
    # campaign news
    run.handle_news(Hit("https://n/5", "Boat appoints Schbang as influencer marketing agency", "Mumbai", NOW, "afaqs"),
                    out, NOW)
    # influencer job and marketing job
    jobs = {("influencer marketing", "India", 0): [Job("https://www.linkedin.com/jobs/view/11", "Influencer Marketing Manager",
                                                       "Lenskart", "https://www.linkedin.com/company/lenskart", "Delhi, India", NOW)],
            ("social media manager", "India", 0): [Job("https://www.linkedin.com/jobs/view/12", "Social Media Manager",
                                                       "Sugar Cosmetics", "https://www.linkedin.com/company/sugar", "Mumbai, India", NOW),
                                                   Job("https://www.linkedin.com/jobs/view/13", "Software Engineer",
                                                       "Zepto", "https://www.linkedin.com/company/zepto", "Mumbai, India", NOW)]}
    f = FakeFetcher(jobs=jobs)
    run.collect_jobs(f, out, NOW)
    run.collect_jobs(f, out, NOW, marketing=True)
    got = {b["Brand / Company"]: (b["Signal"], b["Why Added"]) for b in out.brands + out.jobs}
    assert {b["Brand / Company"] for b in out.jobs} == {"Lenskart", "Sugar Cosmetics"}
    assert got["Acme"][0] == "Direct ask" and "asking for influencer marketing agency" in got["Acme"][1]
    assert got["Nykaa"][0] == "Running influencer campaign" and "partnered with 200 creators" in got["Nykaa"][1]
    assert got["Boat"][0] == "Running influencer campaign" and "Appointed an agency" in got["Boat"][1]
    assert got["Lenskart"][0] == "Hiring for influencer marketing"
    assert got["Sugar Cosmetics"][0] == "Hiring for marketing" and "investing in marketing" in got["Sugar Cosmetics"][1]
    assert "Zepto" not in got
    assert all(b["Why Added"] for b in out.brands + out.jobs)


def test_backfill_explains_old_rows():
    class FakeTab:
        def __init__(self):
            self.updates = []

        def set_cells(self, u):
            self.updates += u
    rows = [{"_row": 2, "Source": "LinkedIn job (Mumbai, India)", "Looking For": "Hiring: Influencer Marketing Manager",
             "Posted On": "2026-10-27", "Post / Job URL": "u1", "Signal": ""},
            {"_row": 3, "Source": "News (afaqs)", "Matched Text": "ICC invites pitches", "Posted On": "2026-10-22",
             "Post / Job URL": "u2", "Signal": ""},
            {"_row": 4, "Signal": "Direct ask", "Post / Job URL": "u3"}]
    t = FakeTab()
    run.backfill(t, rows)
    assert (2, "Signal", "Hiring for influencer marketing") in t.updates
    assert (2, "Why Added", "Hiring a Influencer Marketing Manager in Mumbai, India (job posted 2026-10-27): "
                            "building influencer/creator marketing.") in t.updates
    assert any(r == 3 and h == "Why Added" and "ICC invites pitches" in v for r, h, v in t.updates)
    assert not any(r == 4 for r, _, _ in t.updates)


def test_removed_rows_are_never_added_again():
    removed = [{"From Tab": "github script for brands", "Post / Job URL": "https://www.linkedin.com/jobs/view/x-4483607308",
                "Brand / Company": "Fame Bliss", "Company LinkedIn": "https://www.linkedin.com/company/fame-bliss",
                "Source": "LinkedIn job (Mumbai)"}]
    out = run.Collector([], [], [], removed)
    assert out.seen("https://in.linkedin.com/jobs/view/x-4483607308/")
    assert out.company_listed("Fame Bliss", "https://www.linkedin.com/company/fame-bliss")


def test_in_house_content_creator_jobs_are_marketing_hiring():
    m, i = run.SIGNAL_MARKETING_JOB, run.SIGNAL_INFLUENCER_JOB
    assert run.job_signal("Social Media Content Creator", False) == m
    assert run.job_signal("Video Content Creator (UGC & Growth)", False) == m
    assert run.job_signal("UGC Creator", False) == m
    assert run.job_signal("Influencer Marketing Manager", False) == i
    assert run.job_signal("Creator Partnerships Lead", False) == i
    assert run.job_signal("Senior Manager, Creators and Influencers", False) == i
    assert run.job_signal("Social Media Manager", True) == m


def test_new_rows_get_priority_and_why_kept():
    out = run.Collector([], [], [])
    out.add_brand({"Brand / Company": "Nykaa", "Signal": run.SIGNAL_INFLUENCER_JOB, "Looking For": "Hiring: Influencer Marketing Manager",
                   "Source": "LinkedIn job (Mumbai, India)", "Market": "India", "Post / Job URL": "https://www.linkedin.com/jobs/view/1"})
    r = out.jobs[0]
    assert r["Priority"] == 3 and "Nykaa is a brand" in r["Why Kept"] and "Mumbai, India" in r["Why Kept"]


def test_creator_management_roles_stay_influencer_hiring():
    i, m = run.SIGNAL_INFLUENCER_JOB, run.SIGNAL_MARKETING_JOB
    for t in ("Creator & Social Commerce Manager", "Marketing Manager, Creator & Community", "Social & Creators Lead",
              "TikTok Shop Creator LIVE Manager", "Manager, Integrated Marketing - Social, Creator & Content, OXO"):
        assert run.job_signal(t, False) == i, t
    for t in ("On-Camera Video Creator & Editor", "Content Creator & Social Media Executive", "Reel Creator Fresher",
              "Social Sports Creator & Host, NBC Bay Area"):
        assert run.job_signal(t, False) == m, t
