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
    assert out.brands == [] and out.agencies[0]["Found Via"].startswith("Agency's own post asking for")


def test_existing_sheet_rows_are_not_added_again():
    out = run.Collector([{"Post / Job URL": "https://www.linkedin.com/posts/mamaearth_x-activity-1"}],
                        [{"Profile": "https://www.linkedin.com/in/riya"}], [])
    assert not out.add_brand({"Post / Job URL": "https://www.linkedin.com/posts/mamaearth_x-activity-1"})
    assert not out.add_person("Agency", {"Profile": "https://www.linkedin.com/in/riya"})


def test_urgent_vendor_requirement_post_and_its_pitching_commenters():
    """The real post from 29 Oct 2026 (Niyati Desai): logged out, no headlines are shown."""
    text = ("📢 URGENT REQUIREMENT 📢\n\nWe’re looking for vendors who can connect us with relevant LinkedIn creators and "
            "professionals with strong engagement across marketing, startups, funding, and brand building.\n\n"
            "If you can help, please DM. Looking forward to connecting!\n\n#hiringlinkedinvendors #leads")
    comments = [
        Comment(Person("Abhimanyu singh", "https://www.linkedin.com/in/abhimanyu", "in", "in"),
                "Hi Niyati, this is right in our lane at Viral Hut. We work with LinkedIn creators and professionals"),
        Comment(Person("Tanisha Arya", "https://www.linkedin.com/in/tanisha", "in", "in"),
                "Hi Niyati Desai , this is exactly what we do at anchors . We specialize only in LinkedIn influencer marketing"),
        Comment(Person("Vedika Chawla", "https://www.linkedin.com/in/vedika", "in", "in"),
                "Hi, We have a database of 15000+ creators with most affordable commercials Feel free to connect with us at: hi@x.com"),
        Comment(Person("Piyush Singh", "https://www.linkedin.com/in/piyush", "in", "in"),
                "Hi Niyati, we at TrendCore Media have a strong network of profiles that align with your requirements."),
        Comment(Person("Simrin Singh Chadha", "https://www.linkedin.com/in/simrin", "in", "in"),
                "lets connect on +91-9136655666 / inquiry@thirdeyeblindproductions.com"),
        Comment(Person("Vivek Kumar", "https://www.linkedin.com/in/vivek", "in", "in"), "Navneet Kaur | Biggbell.com"),
        Comment(Person("Sumit Kumar Bharti", "https://www.linkedin.com/in/sumit", "in", "in"), "Rashmi Singh"),
    ]
    post = _post(text, author=Person("Niyati Desai", "https://www.linkedin.com/in/niyati-desai", "in", "in"),
                 comments=comments)
    out = run.Collector([], [], [])
    run.handle_post(FakeFetcher(post), post.url, out, NOW, "search")
    assert len(out.brands) == 1
    assert out.brands[0]["Looking For"] == "LinkedIn influencers/creators, Vendor for creators"
    names = {a["Name"]: a for a in out.agencies}
    assert set(names) == {"Abhimanyu singh", "Vedika Chawla", "Piyush Singh", "Simrin Singh Chadha"}  # anchors skipped
    assert names["Piyush Singh"]["Company (from comment)"] == "TrendCore Media"
    assert names["Abhimanyu singh"]["Company (from comment)"] == "Viral Hut"
    assert "inquiry@thirdeyeblindproductions.com" in names["Simrin Singh Chadha"]["Public Contact"]
    assert out.brands[0]["Agencies in Comments"] == 4


def test_vendor_requirement_wording():
    from brand_intent import intent
    assert intent.wants("Urgent vendor requirement! Know someone who can connect us with linkedin creators ? Please DM me!") == \
        ["LinkedIn influencers/creators", "Vendor for creators"]
    assert intent.wants("Requirement: 20 micro influencers from Bangalore for a food brand, barter + paid") == ["Creators / influencers"]
    assert intent.wants("Looking for an influencer marketing vendor in Mumbai") == ["Influencer marketing agency"]
    assert intent.wants("Great requirement gathering session today with the product team.") == []


def test_agency_ask_also_collects_vendor_commenters():
    agency = Person("Riya", "https://www.linkedin.com/in/riya", "in", "in", "Founder, Influencer Marketing Agency")
    post = _post("We're looking for LinkedIn creators in fintech for a client campaign", author=agency,
                 comments=[Comment(Person("Piyush", "https://www.linkedin.com/in/piyush", "in", "in"),
                                   "we at TrendCore Media have a strong network of fintech creators")])
    out = run.Collector([], [], [])
    run.handle_post(FakeFetcher(post), post.url, out, NOW, "search")
    assert out.brands == [] and {a["Name"] for a in out.agencies} == {"Riya", "Piyush"}
