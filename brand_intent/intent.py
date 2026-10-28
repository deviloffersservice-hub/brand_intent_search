"""Text rules: is this a brand asking for marketing help, which market is it, and who is commenting.

Every rule is a plain regular expression so the sheet's "Why" column can say exactly what matched.
"""
from __future__ import annotations

import re

# --- what the brand is asking for ---------------------------------------------------------------
SEEK = (r"(?:looking for|look(?:ing)? out for|seek(?:s|ing)?|searching for|in search of|on the hunt for|hunting for|"
        r"need(?:s|ed)?|require[sd]?|want(?:s|ed)? to (?:hire|work with|collaborate with|partner with|onboard)|"
        r"hiring|to hire|recommend(?:ation)?s?(?: for)?|suggest(?:ion)?s?(?: for)?|any (?:leads|referrals) (?:for|on)|"
        r"who (?:can|could) (?:help|recommend)|invit(?:e|es|ing) (?:pitches|proposals|agencies)|"
        r"request for proposals?|\bRFP\b|calling all|open to (?:collaborat\w+|partner\w*) with|"
        r"partner(?:ing)? with|collaborat(?:e|ion|ing) with|onboard(?:ing)?)")
GAP = r"[^.!?\n]{0,60}?"  # the target must follow the ask in the same sentence

TARGETS = {
    "LinkedIn influencers/creators": r"(?:linkedin (?:influencers?|creators?|content creators?|top voices?|thought leaders?)|"
                                     r"(?:influencers?|creators?) on linkedin|linkedin ghost ?writers?)",
    "Influencer marketing agency": r"influencer(?:[- ]marketing)? (?:agenc(?:y|ies)|partners?|firms?|platforms?)",
    "Creators / influencers": r"(?:influencers?|content creators?|creators?|ugc creators?|micro[- ]influencers?|"
                              r"nano[- ]influencers?|youtubers?|instagrammers?|bloggers?|kols?)\b"
                              r"(?![- ](?:marketing|agenc|partners?\b|firms?\b|platforms?\b))",
    "Marketing agency": r"(?:(?:digital|social media|performance|growth|content|creative|branding|brand|pr|"
                        r"linkedin|b2b|marketing|seo|advertising|ad) )+(?:agenc(?:y|ies)|partners?|firms?|consultants?|"
                        r"freelancers?)",
}
SEEK_TARGET = {label: re.compile(SEEK + GAP + rx, re.I) for label, rx in TARGETS.items()}

# Agencies advertising themselves: "Looking for an influencer agency? We...", "DM us", "our clients".
SELF_PROMO = re.compile(
    r"(?:looking for|need|searching for)[^.!?\n]{0,60}\?\s*(?:we|our|let|contact|dm|reach|book|check)|"
    r"\b(?:we help|we helped|our agency|our clients|our services|we offer|book a (?:call|demo)|dm us|"
    r"get in touch with us|we are an? (?:agency|influencer)|we're an? (?:agency|influencer)|"
    r"#hiring\b.*\b(?:intern|internship)\b)", re.I | re.S)

PLATFORMS = {"LinkedIn": r"\blinkedin\b", "Instagram": r"\b(?:instagram|insta|reels?)\b",
             "YouTube": r"\b(?:youtube|youtubers?|shorts)\b", "X/Twitter": r"\b(?:twitter|x\.com|tweets?)\b",
             "TikTok": r"\btiktok\b", "Facebook": r"\bfacebook\b"}


def wants(text: str) -> list[str]:
    """Labels of what the text is asking for, most specific first; [] if it isn't asking."""
    if not text or SELF_PROMO.search(text):
        return []
    found = [label for label, rx in SEEK_TARGET.items() if rx.search(text)]
    if "LinkedIn influencers/creators" in found and "Creators / influencers" in found:
        found.remove("Creators / influencers")
    if "Influencer marketing agency" in found and "Marketing agency" in found:
        found.remove("Marketing agency")
    return found


def evidence(text: str) -> str:
    """The sentence fragment that matched, for the sheet."""
    for rx in SEEK_TARGET.values():
        if (m := rx.search(text or "")):
            return text[max(0, m.start() - 20): m.end() + 40].strip()
    return ""


def platforms(text: str) -> list[str]:
    return [name for name, rx in PLATFORMS.items() if re.search(rx, text or "", re.I)]


# --- market: India and/or US ---------------------------------------------------------------------
INDIA = re.compile(r"\b(?:india|indian|bharat|mumbai|bombay|delhi|ncr|gurgaon|gurugram|noida|bangalore|bengaluru|"
                   r"hyderabad|chennai|pune|kolkata|ahmedabad|jaipur|kochi|chandigarh|lucknow|indore)\b|₹|\binr\b|"
                   r"\blakhs?\b|\bcrores?\b", re.I)
US = re.compile(r"\b(?:usa|u\.s\.a?\.?|united states|america|american|new york|nyc|san francisco|bay area|"
                r"los angeles|chicago|austin|seattle|boston|miami|atlanta|dallas|denver|silicon valley)\b", re.I)


def market(country_sub: str, text: str, location: str = "") -> str:
    """"India", "US", "India market" (a brand elsewhere targeting India) or "" (not in scope).

    country_sub is the poster's LinkedIn subdomain ("in" = India, "www" = US), or "" if unknown.
    """
    blob = f"{text} {location}"
    if country_sub == "in" or INDIA.search(location or ""):
        return "India"
    if INDIA.search(blob):
        return "India market"
    if country_sub == "www" or US.search(location or "") or (not country_sub and US.search(blob)):
        return "US"
    return ""


# --- who is commenting ---------------------------------------------------------------------------
AGENCY_WORDS = re.compile(r"\b(?:agency|agencies|marketing|media|digital|influencer marketing|talent management|"
                          r"creative|studios?|advertising|branding|pr\b|public relations|growth partner|"
                          r"social media (?:manager|marketing|agency)|consultancy|solutions)\b", re.I)
AGENCY_ROLE = re.compile(r"\b(?:founder|co-founder|ceo|director|owner|partner|head|lead|manager|business development|"
                         r"bd|account)\b", re.I)
CREATOR_WORDS = re.compile(r"\b(?:creators?|content creator|influencer(?![- ]marketing)|ugc|youtuber|instagrammer|blogger|vlogger|"
                           r"podcast(?:er| host)?|top voice|linkedin top voice|storyteller|ghostwriter|"
                           r"personal brand(?:ing)? coach|\d+(?:\.\d+)?k\+? (?:followers|community|audience))\b", re.I)
OFFER = re.compile(r"\b(?:we can help|we'd love to|we would love to|happy to help|let's connect|dm(?:'d|ed)? you|"
                   r"sent you a (?:dm|message|request)|check your (?:dm|inbox)|our (?:team|agency)|"
                   r"i(?:'d| would) love to|i'm interested|interested|i am a creator|i create)\b", re.I)


def commenter_type(name: str, headline: str, is_company: bool, comment: str = "") -> str:
    """"Agency", "Creator" or "" (neither, e.g. a friend congratulating)."""
    who = f"{name} | {headline}"
    if is_company:
        return "Agency" if AGENCY_WORDS.search(who) or OFFER.search(comment) else ""
    if AGENCY_WORDS.search(headline) and AGENCY_ROLE.search(headline) and not CREATOR_WORDS.search(headline):
        return "Agency"
    if CREATOR_WORDS.search(headline) or re.search(r"\b(?:i am|i'm) an? (?:creator|influencer)\b", comment, re.I):
        return "Creator"
    if AGENCY_WORDS.search(headline) and AGENCY_ROLE.search(headline):
        return "Agency"
    return ""


AGENCY_NAME = re.compile(r"\b(?:agency|agencies|influencer marketing|talent management|media network|creator network|"
                         r"digital marketing services|communications|comms|advertising|ad ?works|creatives?|"
                         r"public relations|pr|media (?:group|labs?|house|works)|marketing (?:group|solutions|labs?)|"
                         r"digital (?:media|solutions|labs?)|influencers?)\b", re.I)
RECRUITER_NAME = re.compile(r"\b(?:talent (?:acquisition|destination|solutions|partners)|careers?|staffing|recruit\w*|"
                            r"placements?|hr (?:services|solutions|consult\w*)|manpower|headhunt\w*|hiring partners?|"
                            r"human capital\w*|job(?:s| portal)?)\b", re.I)
# Big agency networks whose names don't say "agency".
KNOWN_AGENCIES = {"dentsu", "wpp", "ogilvy", "publicis", "omnicom", "havas", "ipg", "mccann", "leo burnett", "kinnect",
                  "zeno group", "vaynerx", "vaynermedia", "edelman", "weber shandwick", "group m", "groupm", "mindshare",
                  "wavemaker", "madison world", "dentsu creative", "social beat", "schbang", "wondrlab", "monk-e",
                  "later", "grin", "aspire", "creatoriq", "upfluence", "influur", "obviously", "whalar", "billion dollar boy"}


def looks_like_agency(name: str, headline: str = "", slug: str = "") -> bool:
    """For posters and job advertisers: an agency, influencer platform or recruiter, not a brand.

    name: person or company name; headline: a person's LinkedIn headline (only its "at <Company>"
    part and the word "agency" count, so "Head of Marketing at Mamaearth" stays a brand);
    slug: a company page slug ("sopastelmarketing").
    """
    company = company_from_headline(headline)
    who = f"{name} | {company}"
    if re.search(r"\bagenc(?:y|ies)\b", headline, re.I):
        return True
    if {name.strip().lower(), company.lower()} & KNOWN_AGENCIES:
        return True
    if AGENCY_NAME.search(who) or RECRUITER_NAME.search(who):
        return True
    return bool(re.search(r"marketing|agency|career|recruit|staffing|talent", re.sub(r"[^a-z]", "", slug.lower())))


# --- news and trade press: agency pitches and mandates -------------------------------------------
PITCH = re.compile(r"(?:calls? for|invites?|issues?|opens?|kicks? off|initiates?|floats?|announces?)"
                   r"[^.!?\n]{0,40}(?:pitch(?:es)?|rfps?|proposals?|mandates?)|"
                   r"(?:seeks?|seeking|looking for|on the hunt for|scouting for|hunts? for)"
                   r"[^.!?\n]{0,40}(?:agenc(?:y|ies)|partners?)", re.I)
BRAND_BEFORE = re.compile(r"^(.{2,60}?)\s+(?:calls?|invites?|issues?|opens?|kicks? off|initiates?|floats?|"
                          r"announces?|seeks?|is seeking|looking|on the hunt|scouting|hunts?)\b", re.I)


def news_wants(title: str, snippet: str = "") -> list[str]:
    blob = f"{title}. {snippet}"
    found = wants(blob)
    if not found and PITCH.search(blob):
        found = ["Agency pitch / mandate"]
    return found


def brand_from_title(title: str) -> str:
    m = BRAND_BEFORE.search(title or "")
    return m.group(1).strip(" :-–|\"'") if m else ""


def company_from_headline(headline: str) -> str:
    """'Head of Marketing at Mamaearth | ...' -> 'Mamaearth'."""
    m = re.search(r"(?:\bat\b|@)\s*([^|,•·/\-–]+)", headline or "")
    return m.group(1).strip() if m else ""


def reddit_commenter_type(comment: str) -> str:
    """Reddit has no headlines, so judge by what the commenter says about themselves."""
    if re.search(r"\b(?:my|our) (?:agency|team|firm|company)\b|\bwe(?:'re| are) an? [^.]{0,40}agency\b|"
                 r"\bwe (?:run|help|work with) [^.]{0,40}(?:brands|creators|influencers|campaigns)\b", comment, re.I):
        return "Agency"
    if re.search(r"\b(?:i(?:'m| am) an? [^.]{0,30}(?:creator|influencer|youtuber|instagrammer|blogger)|"
                 r"my (?:channel|audience|followers|page)|i create (?:content|videos|ugc))\b", comment, re.I):
        return "Creator"
    return ""
