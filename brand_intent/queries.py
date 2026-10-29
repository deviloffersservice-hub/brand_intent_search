"""Search phrases. Each run takes the next slice of each list (rotating), so every phrase gets used
over a day without any single run asking too much of the search engines."""

# Brands posting on LinkedIn that they want an agency or creators.
LINKEDIN_POSTS = [
    '"looking for an influencer marketing agency"',
    '"looking for influencer marketing agency"',
    '"recommend an influencer marketing agency"',
    '"influencer marketing agency" recommendations',
    '"looking for LinkedIn influencers"',
    '"looking for LinkedIn creators"',
    '"LinkedIn creators" collaborate brand',
    '"looking for creators" collaborate',
    '"looking for influencers" collaborate',
    '"looking for UGC creators"',
    '"looking for micro influencers"',
    '"want to collaborate with influencers"',
    '"looking for a marketing agency"',
    '"looking for a digital marketing agency"',
    '"looking for a social media agency"',
    '"looking for a LinkedIn marketing agency"',
    '"LinkedIn ghostwriter" looking for',
    '"looking for a performance marketing agency"',
    '"looking for influencer marketing agency" India',
    '"looking for influencers" India brand',
    '"looking for creators" India brand',
    '"digital marketing agency" recommendations Mumbai OR Bangalore OR Delhi',
    '"marketing agency" recommendations startup India',
    '"influencer marketing agency" India "looking for"',
]

# Posts asking for vendors/creators the way people actually write them ("URGENT REQUIREMENT", "vendor
# requirement", "know someone who can connect us with LinkedIn creators"). Search engines do answer these.
VENDOR_ASKS = [
    '"urgent requirement" linkedin creators',
    '"urgent requirement" influencer marketing',
    '"vendor requirement" creators',
    '"looking for vendors" creators',
    '"looking for vendors" influencer',
    '#hiringlinkedinvendors',
    '"requirement" "linkedin influencers"',
    '"connect us with" linkedin creators',
    '"urgent requirement" influencers brand',
    '"looking for linkedin creators"',
    '"influencer requirement" brand',
    '"creators required" campaign',
]

# Topical searches that return recent LinkedIn posts about influencer/creator marketing: starting
# points for the related-posts crawl (search engines rarely answer the exact-ask phrases above).
LINKEDIN_SEEDS = [
    "influencer marketing",
    "creator marketing",
    "UGC creators brand",
    "influencer campaign brand",
    "LinkedIn creators",
    "LinkedIn influencer marketing",
    "brand collaboration influencers",
    "influencer marketing India",
    "D2C brand influencer",
    "creator economy brands",
    "B2B influencer marketing",
    "looking for creators",
]

# Reddit threads where a brand or founder asks for an agency or creators.
REDDIT = [
    "influencer marketing agency recommendation",
    "looking for influencers for my brand",
    "looking for marketing agency India",
    "influencer marketing agency India startup",
    "LinkedIn marketing agency recommendation",
    "looking for UGC creators",
    "digital marketing agency recommendation India",
    "hire influencer marketing agency",
]

# News and trade press: brands calling agency pitches or seeking marketing partners.
NEWS = [
    "calls for agency pitch influencer",
    "influencer marketing mandate agency",
    "invites agencies pitch digital mandate",
    "brand seeks influencer marketing agency",
    "creative mandate pitch India brand",
    "social media mandate agency India",
    "RFP influencer marketing agency",
    "brand looking for marketing agency India",
]

# LinkedIn jobs: a company hiring for these roles is investing in influencer/creator marketing.
JOB_KEYWORDS = [
    "influencer marketing",
    "creator partnerships",
    "creator marketing",
    "influencer marketing manager",
    "influencer relations",
    "brand partnerships influencer",
    "UGC creator",
    "KOL marketing",
    "affiliate and influencer",
    "social media influencer",
    "talent partnerships creator",
    "LinkedIn marketing",
    "LinkedIn content",
]
JOB_LOCATIONS = ["India", "United States"]

# Broader signal, used last to fill a run up to its target: companies hiring for marketing roles.
MARKETING_JOB_KEYWORDS = [
    "social media manager",
    "social media marketing",
    "digital marketing manager",
    "brand manager",
    "content marketing manager",
    "performance marketing",
    "growth marketing",
    "head of marketing",
    "community manager",
]

# Brands already doing influencer marketing: campaign launches and agency appointments in the news.
CAMPAIGN_NEWS = [
    "launches influencer campaign",
    "creator-led campaign brand",
    "appoints influencer marketing agency",
    "bags influencer mandate",
    "influencer campaign India brand",
    "partners with creators campaign",
    "UGC campaign brand launch",
    "influencer marketing mandate win",
]


def rotation(items: list[str], k: int, slot: int) -> list[str]:
    """k items starting at a slot-dependent offset, wrapping around."""
    if not items:
        return []
    start = (slot * k) % len(items)
    return [items[(start + i) % len(items)] for i in range(min(k, len(items)))]
