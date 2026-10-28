from datetime import datetime, timedelta, timezone

from brand_intent import run
from brand_intent.linkedin import Comment, Person, Post

NOW = datetime.now(timezone.utc)


class FakeFetcher:
    def __init__(self, post):
        self._post = post

    def post(self, url):
        return self._post


def _post(text, author=None, days_old=2, comments=()):
    author = author or Person("Mamaearth", "https://www.linkedin.com/company/mamaearth", "company", "in")
    return Post(url="https://www.linkedin.com/posts/mamaearth_x-activity-1", author=author,
                published=NOW - timedelta(days=days_old), text=text, comments=list(comments))


def test_brand_post_with_agency_and_creator_comments():
    comments = [
        Comment(Person("Spark Media", "https://www.linkedin.com/in/riya", "in", "in",
                       "Founder | Influencer Marketing Agency"), "We'd love to help!"),
        Comment(Person("Aman", "https://www.linkedin.com/in/aman", "in", "in", "Content Creator | 80K"), "Interested!"),
        Comment(Person("John", "https://www.linkedin.com/in/john", "in", "www", "Engineer at Google"), "Congrats"),
    ]
    out = run.Collector([], [], [])
    post = _post("We are looking for an influencer marketing agency for our winter launch.", comments=comments)
    run.handle_post(FakeFetcher(post), post.url, out, NOW, "search")
    assert len(out.brands) == 1
    b = out.brands[0]
    assert b["Brand / Company"] == "Mamaearth" and b["Market"] == "India"
    assert b["Agencies in Comments"] == 1 and b["Creators in Comments"] == 1
    assert [a["Name"] for a in out.agencies] == ["Spark Media"] and [c["Name"] for c in out.creators] == ["Aman"]
    # the same post and people again: no duplicates
    run.handle_post(FakeFetcher(post), post.url, out, NOW, "search")
    assert len(out.brands) == 1 and len(out.agencies) == 1 and len(out.creators) == 1


def test_old_or_non_asking_or_out_of_market_posts_are_skipped():
    out = run.Collector([], [], [])
    for post in (_post("Looking for an influencer marketing agency", days_old=20),
                 _post("Proud of our team!"),
                 _post("Looking for an influencer marketing agency",
                       author=Person("Acme GmbH", "https://www.linkedin.com/company/acme", "company", "de"))):
        run.handle_post(FakeFetcher(post), post.url, out, NOW, "search")
    assert out.brands == []
    assert set(out.skipped) == {"post older than 14 days", "post isn't an ask", "not India/US"}


def test_agency_posting_for_creators_goes_to_agencies():
    out = run.Collector([], [], [])
    agency = Person("Riya", "https://www.linkedin.com/in/riya", "in", "in", "Founder, Influencer Marketing Agency")
    post = _post("We're looking for fashion creators in Mumbai for a brand campaign", author=agency)
    run.handle_post(FakeFetcher(post), post.url, out, NOW, "search")
    assert out.brands == [] and out.agencies[0]["Found Via"] == "Agency's own post"


def test_existing_sheet_rows_are_not_added_again():
    out = run.Collector([{"Post / Job URL": "https://www.linkedin.com/posts/mamaearth_x-activity-1"}],
                        [{"Profile": "https://www.linkedin.com/in/riya"}], [])
    assert not out.add_brand({"Post / Job URL": "https://www.linkedin.com/posts/mamaearth_x-activity-1"})
    assert not out.add_person("Agency", {"Profile": "https://www.linkedin.com/in/riya"})
