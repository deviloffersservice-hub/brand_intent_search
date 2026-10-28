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
