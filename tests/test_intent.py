from brand_intent import intent


def test_brand_asks_are_recognised():
    assert intent.wants("We are looking for an influencer marketing agency for our Diwali campaign.") == \
        ["Influencer marketing agency"]
    assert intent.wants("Looking for LinkedIn creators in fintech to partner with!") == ["LinkedIn influencers/creators"]
    assert intent.wants("We want to collaborate with micro-influencers on Instagram") == ["Creators / influencers"]
    assert intent.wants("Can anyone recommend a good digital marketing agency in Bangalore?") == ["Marketing agency"]


def test_agency_self_promotion_and_chatter_are_ignored():
    assert intent.wants("Looking for an influencer marketing agency? We help brands scale. DM us!") == []
    assert intent.wants("Great post, congrats on the launch!") == []


def test_market():
    assert intent.market("in", "anything") == "India"
    assert intent.market("uk", "We want creators for our launch in India") == "India market"
    assert intent.market("www", "We need an agency") == "US"
    assert intent.market("de", "We need an agency") == ""
    assert intent.market("", "", "Mumbai, Maharashtra, India") == "India"
    assert intent.market("", "", "New York, NY") == "US"


def test_commenters():
    assert intent.commenter_type("Riya", "Founder @ Spark Media | Influencer Marketing Agency", False) == "Agency"
    assert intent.commenter_type("Aman", "LinkedIn Top Voice | Content Creator", False) == "Creator"
    assert intent.commenter_type("Brandly", "", True, "We'd love to help! Sent you a DM") == "Agency"
    assert intent.commenter_type("John", "Software Engineer at Google", False) == ""
    assert intent.reddit_commenter_type("Our agency ran 40 creator campaigns last year") == "Agency"
    assert intent.reddit_commenter_type("I'm a fitness creator with 50k followers") == "Creator"


def test_agencies_and_recruiters_are_not_brands():
    assert intent.looks_like_agency("Kinnect")
    assert intent.looks_like_agency("Koffeetech Communications")
    assert intent.looks_like_agency("So Pastel", slug="sopastelmarketing")
    assert intent.looks_like_agency("Talent Destination")
    assert not intent.looks_like_agency("Huda Beauty", slug="hudabeauty")
    assert not intent.looks_like_agency("Priya", "Head of Marketing at Mamaearth")


def test_news_pitches():
    assert intent.news_wants("Mamaearth calls for digital creative pitch") == ["Agency pitch / mandate"]
    assert intent.brand_from_title("Tata Motors seeks influencer marketing agency") == "Tata Motors"


def test_job_titles_and_creator_economy_talk_are_not_asks():
    assert intent.wants("We're hiring a Head of Creator Media in NYC") == []
    assert intent.wants("So hire a Head of Creator Media. In two years it will be obvious") == []
    assert intent.wants("We are hiring a creator partnerships manager") == []
    assert intent.wants("Hiring creators for our new skincare launch, DM if interested") == ["Creators / influencers"]


# --- cases from the code review -------------------------------------------------------------------
import pytest  # noqa: E402


@pytest.mark.parametrize("text, expected", [
    ("Looking for UGC creators for our skincare brand. DM us your portfolio!", ["Creators / influencers"]),
    ("Looking for micro influencers in Mumbai. We offer free products + paid collabs.", ["Creators / influencers"]),
    ("At Mamaearth we help new parents. Looking for mom influencers for our launch", ["Creators / influencers"]),
    ("Looking for an influencer agency in Mumbai? Our budget is 5L, please refer.", ["Influencer marketing agency"]),
    ("Need an agency for influencer marketing for our D2C brand", ["Influencer marketing agency"]),
    ("Kindly refer good influencer marketing agencies in Delhi", ["Influencer marketing agency"]),
    ("Please suggest good agencies for influencer marketing", ["Influencer marketing agency"]),
    ("Looking for an agency to handle our influencer campaigns", ["Influencer marketing agency"]),
    ("Can anyone recommend a good digital marketing agency in Bangalore?", ["Marketing agency"]),
])
def test_real_asks(text, expected):
    assert intent.wants(text) == expected


@pytest.mark.parametrize("text", [
    "Every D2C brand needs creators, not ads",
    "Our collaboration with 50 creators drove 2M views",
    "I recommend influencers to every founder",
    "Brands need influencer marketing agencies that understand ROI",
    "We manage our influencer partnerships in-house now",
    "Looking for brand partners and sponsors for our college fest in Delhi",
    "I'm a LinkedIn creator and I partner with brands as a LinkedIn creator. Brands, let's collaborate!",
    "Looking for an influencer marketing agency? We help D2C brands scale with creators.",
    "We are an influencer marketing agency working with 200 brands. Book a call.",
])
def test_not_asks(text):
    assert intent.wants(text) == []


def test_us_mentions_and_subreddits():
    assert intent.market("", "We're a U.S. brand looking for creators") == "US"
    assert intent.market("", "US-based startup needs an agency") == "US"
    assert intent.market("", "bakery in Texas") == "US"


def test_brand_marketers_are_not_agencies():
    assert intent.commenter_type("Riya", "Marketing Manager at Mamaearth", False, "Congrats team") == ""
    assert intent.commenter_type("Kunal", "Head of Brand Marketing at Nykaa", False, "Great") == ""
    assert intent.commenter_type("Swiggy", "", True, "Interested") == ""
    assert intent.commenter_type("Spark Media", "", True, "Congrats") == "Agency"
    assert intent.commenter_type("Riya", "Founder at Spark Media", False, "") == "Agency"
    assert not intent.looks_like_agency("Priya", "Brand Manager at Mamaearth | ex-agency")


def test_commenters_without_headlines_are_judged_by_what_they_say():
    asked_creators = ["Creators / influencers"]
    asked_agency = ["Influencer marketing agency"]
    assert intent.commenter_type("Aman", "", False, "Interested! Sent you a DM", asked_creators) == "Creator"
    assert intent.commenter_type("Aman", "", False, "Interested! Sent you a DM", asked_agency) == ""
    assert intent.commenter_type("Neha", "", False, "We'd love to help, our team has run 40 campaigns", asked_agency) == "Agency"
    assert intent.commenter_type("Bob", "", False, "Congrats!", asked_creators) == ""


def test_known_agencies_with_suffixes():
    for name in ("Ogilvy India", "Dentsu India", "Havas Media India", "GroupM India", "Schbang Digital",
                 "Social Beat Digital Marketing LLP"):
        assert intent.looks_like_agency(name), name
    assert intent.looks_like_agency("Raj", "CEO at Pinnacle Marketing")


def test_company_from_headline():
    assert intent.company_from_headline("Head of Growth at Coca-Cola India") == "Coca-Cola India"
    assert intent.company_from_headline("Great at storytelling | Marketing Lead at Nykaa") == "Nykaa"
    assert intent.company_from_headline("reach me at hello@brand.com") == ""


def test_news_brand_names():
    assert intent.brand_from_title("Exclusive: Bisleri calls for creative pitch") == "Bisleri"
    assert intent.brand_from_title("Why brands are looking for agencies") == ""
    assert intent.brand_from_title("Swiggy's Instamart is looking for a creative agency") == "Swiggy's Instamart"


@pytest.mark.parametrize("text", [
    "Running Meta Ads on a small budget? You still don't need a full-time digital marketing agency on a monthly retainer.",
    "For example: - A business searching for a marketing agency. These users may already have a clear need.",
    "And maybe that's the shift I need to make as a LinkedIn content creator.",
    "You don't need creator retainers to win on TikTok Shop.",
    "Most brands are looking for creators who actually convert.",
    "We don't need an agency, we built this in-house.",
])
def test_advice_examples_and_self_descriptions_are_not_asks(text):
    assert intent.wants(text) == []


def test_own_voice_asks_still_count():
    assert intent.wants("We are looking for creators for our launch. Most brands get this wrong.") == ["Creators / influencers"]
    assert intent.wants("Can anyone recommend a LinkedIn ghostwriter for our CEO?") == ["LinkedIn influencers/creators"]
    assert intent.wants("Our team is looking for an influencer marketing agency in Mumbai") == ["Influencer marketing agency"]


def test_agency_sales_copy_is_not_an_ask():
    ad = ("🚀 SEO Services for Social Media Influencers! At Hyperledger IT - Digital Marketing Agency, we provide professional "
          "SEO Services for Social Media Influencers. 🌟 Our SEO Services for Influencers Include: ... "
          "Looking for an SEO Company for Influencers? Contact us today!")
    assert intent.wants(ad) == []
    # a brand that mentions what it offers creators is still asking
    assert intent.wants("Looking for UGC creators for our skincare brand. We offer free products + paid collabs.") == \
        ["Creators / influencers"]
