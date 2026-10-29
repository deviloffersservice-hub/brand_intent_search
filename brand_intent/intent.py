"""Text rules: is this a brand asking for marketing help, which market is it, and who is commenting.

Every rule is a plain regular expression so the sheet's "Matched Text" column can show what matched.
"""
from __future__ import annotations

import re

# --- what the brand is asking for ---------------------------------------------------------------
# An ask, in the poster's own voice. Bare "need"/"recommend"/"collaboration with" are left out on
# purpose: "every brand needs creators" or "our collaboration with 50 creators" are opinions/reports.
SEEK = (r"(?:looking for|look(?:ing)? out for|seek(?:s|ing)?|searching for|in search of|on the hunt for|hunting for|"
        r"(?:we|i|our (?:brand|team|startup|company|client)) (?:urgently )?(?:need|require|are looking)|"
        r"need(?:ing)? (?:an?|some|a few|good|the right|reliable)|require[sd]? (?:an?|some)|"
        r"want(?:s|ed)? to (?:hire|work with|collaborate with|partner with|onboard)|"
        r"(?:looking|keen|excited|open) to (?:hire|work with|collaborate with|partner with|onboard)|"
        r"hiring|to hire|"
        r"(?:can (?:anyone|you|someone)|please|pls|kindly|any(?:one)?|could you) (?:recommend|suggest|refer)|"
        r"recommendations? (?:for|on)|suggestions? (?:for|on)|any (?:leads|referrals) (?:for|on)|"
        r"who (?:can|could) (?:help|recommend)|invit(?:e|es|ing) (?:pitches|proposals|agencies)|"
        r"request for proposals?|\bRFP\b|calling all|open to (?:collaborat\w+|partner\w*) with|onboarding|"
        # "URGENT REQUIREMENT: LinkedIn creators with 10k+ followers", "Know someone who can connect us with ..."
        r"(?:urgent |immediate )?(?:vendor |creator |influencer )?requirements?(?: for)?\s*[:\-–]?|"
        r"(?:urgently |immediately )?(?:required|wanted|needed)\s*[:\-–]|"
        r"(?:know|any(?:one)?|does anyone know) (?:someone|anyone|anybody|of any|any)(?: \w+)? (?:who|that) can|"
        r"vendors? who can|someone who can|connect us with)")
GAP = r"[^.!?\n]{0,60}?"  # the target must follow the ask in the same sentence

ROLE_AFTER = (r"(?![- ](?:marketing|agenc|partners?\b|partnerships?\b|firms?\b|platforms?\b|media\b|economy|"
              r"programs?\b|funds?\b|studios?\b|tools?\b|head\b|managers?\b|leads?\b|directors?\b|coordinators?\b|"
              r"specialists?\b|executives?\b|interns?\b|relations\b|strategists?\b|success\b))")
TARGETS = {
    "LinkedIn influencers/creators": r"(?:linkedin (?:influencers?|creators?|content creators?|top voices?|thought leaders?)|"
                                     r"(?:influencers?|creators?) on linkedin|linkedin ghost ?writers?)\b" + ROLE_AFTER,
    "Influencer marketing agency": r"(?:influencer(?:[- ]marketing)? (?:agenc(?:y|ies)|partners?|firms?|platforms?|"
                                   r"vendors?)\b|"
                                   r"agenc(?:y|ies) (?:for|to (?:handle|run|manage|execute))[^.!?\n]{0,30}"
                                   r"(?:influencer|creator))",
    "Creators / influencers": r"(?:influencers?|content creators?|creators?|ugc creators?|micro[- ]influencers?|"
                              r"nano[- ]influencers?|youtubers?|instagrammers?|bloggers?|kols?)\b" + ROLE_AFTER,
    # A vendor/agency/partner to supply creators: "vendors who can connect us with LinkedIn creators"
    "Vendor for creators": r"(?:vendors?|suppliers?|partners?|agenc(?:y|ies))\b[^.!?\n]{0,70}?"
                           r"(?:creators?|influencers?|kols?)\b",
    "Marketing agency": r"(?:(?:(?:digital|social media|performance|growth|content|creative|branding|pr|linkedin|b2b|"
                        r"marketing|seo|advertising|ad) )+(?:agenc(?:y|ies)|firms?|consultants?|freelancers?)|"
                        r"\ban agency\b|\bagencies\b)\b",
}
SEEK_TARGET = {label: re.compile(SEEK + GAP + rx, re.I) for label, rx in TARGETS.items()}
# "Looking for an agency to handle our influencer campaigns" asks for an agency, not for creators.
SEEK_TARGET["Creators / influencers"] = re.compile(SEEK + r"(?:(?!agenc)[^.!?\n]){0,60}?" + TARGETS["Creators / influencers"],
                                                   re.I)

# Agencies advertising themselves: "Looking for an influencer agency? We help...", "our agency",
# "book a call". A brand may well say "DM us" or "we offer free products", so those don't count.
SELF_PROMO = re.compile(
    r"(?:looking for|need|searching for|struggling to find)[^.!?\n]{0,60}\?\s*"
    r"(?:we (?:help|can|offer|are|do|make)|we're|look no further|let us|let's talk|contact us|dm us|"
    r"reach out to us|book a|check out|you're in the right place|our (?:agency|team) (?:can|helps?))|"
    r"\b(?:our agency|our clients|we are an? (?:\w+ ){0,3}agency|we're an? (?:\w+ ){0,3}agency|"
    r"book a (?:free )?(?:call|demo|consultation)|#hiring\b.*\b(?:intern|internship)\b)", re.I | re.S)
# A creator pitching themselves to brands ("I partner with brands as a LinkedIn creator").
CREATOR_PITCH = re.compile(r"\b(?:i(?:'m| am) an? (?:\w+ ){0,3}(?:creator|influencer)|"
                           r"(?:brands|companies),? (?:let's|lets) (?:collaborate|work together)|"
                           r"open (?:for|to) (?:brand )?collaborations?\b(?! with))", re.I)

PLATFORMS = {"LinkedIn": r"\blinkedin\b", "Instagram": r"\b(?:instagram|insta|reels?)\b",
             "YouTube": r"\b(?:youtube|youtubers?|shorts)\b", "X/Twitter": r"\b(?:twitter|x\.com|tweets?)\b",
             "TikTok": r"\btiktok\b", "Facebook": r"\bfacebook\b"}


# Who is asking: real asks are in the poster's own voice. Advice ("you don't need an agency"),
# examples ("a business searching for a marketing agency") and self-descriptions ("the shift I need
# to make as a LinkedIn creator") are not.
NEGATION = re.compile(r"\b(?:don'?t|do not|doesn'?t|does not|didn'?t|no need|never|without|stop|isn'?t|not|won'?t)\b"
                      r"[^.!?\n]{0,15}$", re.I)
OTHER_SUBJECT = re.compile(r"\b(?:you|your|someone|somebody|a business|businesses|brands|companies|startups|founders|"
                           r"marketers|people|users|customers|buyers|homeowners?|most|many|every|they|he|she|them|"
                           r"agencies|clients)\b", re.I)
SELF_AS = re.compile(r"\bas an?\s+(?:[\w-]+\s+){0,3}$", re.I)


def _own_ask(text: str, m: re.Match) -> bool:
    sentence_start = max(text.rfind(c, 0, m.start()) for c in ".!?\n") + 1
    before = text[sentence_start:m.start()]
    if NEGATION.search(before) or (OTHER_SUBJECT.search(before) and not re.search(r"\b(?:we|i|our|my|us)\b", before, re.I)):
        return False
    # the words between the ask and its target, e.g. "to make as a " in "I need to make as a LinkedIn creator"
    gap = re.match(SEEK + r"(.*)$", m.group(0), re.I | re.S)
    tail = text[m.start():m.end()]
    for target in TARGETS.values():
        t = re.search(target, tail, re.I)
        if t and SELF_AS.search(tail[:t.start()]):
            return False
    return gap is not None


def wants(text: str) -> list[str]:
    """Labels of what the text is asking for, most specific first; [] if it isn't asking."""
    if not text or SELF_PROMO.search(text) or CREATOR_PITCH.search(text):
        return []
    found = [label for label, rx in SEEK_TARGET.items()
             if any(_own_ask(text, m) for m in rx.finditer(text))]
    if "LinkedIn influencers/creators" in found and "Creators / influencers" in found:
        found.remove("Creators / influencers")
    if "Influencer marketing agency" in found and "Marketing agency" in found:
        found.remove("Marketing agency")
    if "Influencer marketing agency" in found and "Vendor for creators" in found and \
            not re.search(r"\bvendors?\b", text, re.I):
        found.remove("Vendor for creators")
    # "Urgent vendor requirement! Know someone who can connect us with LinkedIn creators?"
    if found and "Vendor for creators" not in found and re.search(r"\bvendors?\b", text, re.I) and \
            set(found) & {"LinkedIn influencers/creators", "Creators / influencers"}:
        found.append("Vendor for creators")
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
                   r"hyderabad|chennai|pune|kolkata|ahmedabad|jaipur|kochi|chandigarh|lucknow|indore|surat)\b|₹|\binr\b|"
                   r"\blakhs?\b|\bcrores?\b|\b\d+(?:\.\d+)?\s?l\b(?= budget)", re.I)
US = re.compile(r"(?<![a-z])(?:usa|u\.s\.(?:a\.)?|us-based|us based|united states|america|american|new york|nyc|"
                r"san francisco|bay area|los angeles|chicago|austin|seattle|boston|miami|atlanta|dallas|houston|"
                r"denver|silicon valley|california|texas|florida|new jersey|washington dc|colorado|arizona|"
                r"illinois|massachusetts|georgia, us)(?![a-z])", re.I)


def market(country_sub: str, text: str, location: str = "") -> str:
    """"India", "US", "India market" (a brand elsewhere targeting India) or "" (not in scope).

    country_sub is the poster's LinkedIn subdomain ("in" = India; "www" is LinkedIn's US/default
    host), or "" if unknown.
    """
    blob = f"{text} {location}"
    if country_sub == "in" or INDIA.search(location or ""):
        return "India"
    if INDIA.search(blob):
        return "India market"
    if country_sub == "www" or US.search(location or "") or (not country_sub and US.search(blob)):
        return "US"
    return ""


# --- agencies, recruiters and platforms (not brands) -------------------------------------------
AGENCY_NAME = re.compile(r"\b(?:agency|agencies|influencer marketing|talent management|media|creator network|"
                         r"marketing|communications|comms|advertising|ad ?works|creatives?|public relations|pr|"
                         r"digital (?:media|solutions|labs?)|influencers?|branding|studios?|interactive|"
                         r"growth partners|technolabs|digiworld)\b", re.I)
RECRUITER_NAME = re.compile(r"\b(?:talent (?:acquisition|destination|solutions|partners)|careers?|staffing|recruit\w*|"
                            r"placements?|hr|hr (?:services|solutions|consult\w*)|manpower|headhunt\w*|hiring partners?|"
                            r"hiring solutions|human capital\w*|job(?:s| portal)?|jobgether|professional search|"
                            r"search partners|consultan(?:t|ts|cy)|robert half|aquent|jobot|lhh)\b", re.I)
# Big agency networks and influencer platforms whose names don't say "agency" (matched as a prefix:
# "Ogilvy India", "Dentsu Creative" ...).
KNOWN_AGENCIES = ("dentsu", "wpp", "ogilvy", "publicis", "omnicom", "havas", "ipg", "mccann", "leo burnett", "kinnect",
                  "zeno group", "vaynerx", "vaynermedia", "edelman", "weber shandwick", "group m", "groupm", "mindshare",
                  "wavemaker", "madison world", "social beat", "schbang", "wondrlab", "monk-e", "later", "grin",
                  "aspire", "creatoriq", "upfluence", "influur", "obviously", "whalar", "billion dollar boy", "yaap",
                  "confluencr", "the moms co-lab", "agentio", "ddb", "bbdo", "tbwa", "fcb", "grey", "lowe lintas",
                  "dentsu india", "isobar", "iprospect", "performics", "carat", "zenith", "starcom", "spark foundry")
KNOWN_RE = re.compile(r"^(?:%s)\b" % "|".join(re.escape(a) for a in KNOWN_AGENCIES), re.I)


def company_from_headline(headline: str) -> str:
    """'Head of Marketing at Mamaearth | ex-HUL' -> 'Mamaearth'. Looks at each '|' part for
    '<role> at/@ <Capitalised Company>' and keeps hyphens ('Coca-Cola India')."""
    for part in re.split(r"\s*[|•·]\s*", headline or ""):
        m = re.search(r"(?:\bat\b|@)\s*([A-Z0-9][\w&.'’\-– ]{0,60})", part)
        if m and "@" not in m.group(1) and not re.search(r"\.(?:com|in|io|co)\b", m.group(1)):
            return re.split(r"\s[-–]\s|,", m.group(1))[0].strip()
    return ""


def looks_like_agency(name: str, headline: str = "", slug: str = "") -> bool:
    """For posters and job advertisers: an agency, influencer platform or recruiter, not a brand.

    name: person or company name; headline: a person's LinkedIn headline (only its company part
    and "agency founder"-style wording count, so "Head of Marketing at Mamaearth" stays a brand);
    slug: a company page slug ("sopastelmarketing").
    """
    company = company_from_headline(headline)
    if re.search(r"(?<!ex-)(?<!ex )(?<!former )\bagenc(?:y|ies)\b", headline or "", re.I):
        return True
    for who in (name, company):
        if who and (KNOWN_RE.search(who.strip()) or AGENCY_NAME.search(who) or RECRUITER_NAME.search(who)):
            return True
    return bool(re.search(r"marketing|agency|career|recruit|staffing|talent", re.sub(r"[^a-z]", "", slug.lower())))


# --- who is commenting ---------------------------------------------------------------------------
CREATOR_WORDS = re.compile(r"\b(?:creators?|content creator|influencer(?![- ]marketing)|ugc|youtuber|instagrammer|"
                           r"blogger|vlogger|podcast(?:er| host)?|top voice|storyteller|ghostwriter|"
                           r"\d+(?:\.\d+)?k\+? (?:followers|community|audience))\b", re.I)
# A commenter pitching a service, in a business voice: "this is exactly what we do at X", "we at TrendCore Media
# have a strong network", "we have a database of 15000+ creators", "connect with us at ...".
VENDOR_PITCH = re.compile(
    r"\b(?:we at|here at|exactly what we do|right in our lane|in our wheelhouse|we (?:work|worked) with|we have (?:a|an) "
    r"(?:database|network|roster|pool|community)|database of|network of [\d,]+|we (?:specialize|specialise|connect|"
    r"provide|offer|manage|run|deliver|help)|our (?:network|database|team|agency|roster|clients)|connect with us|"
    r"reach (?:out to )?us|contact us|feel free to (?:connect|reach)|we'?ve (?:done|run|worked)|(?:dm|call|whatsapp) us)\b",
    re.I)
CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|(?:\+91|\+1)?[\s-]?\d{5}[\s-]?\d{5}|\b(?:www\.)?[\w-]+\.(?:com|in|io|co|ai)\b",
                     re.I)
AGENCY_OFFER = re.compile(r"\b(?:we can help|we(?:'d| would) love to (?:help|work|partner|connect|discuss)|"
                          r"happy to help|our (?:team|agency)|we (?:specialise|specialize|run|manage|work with)|"
                          r"we've (?:worked|run|helped)|let's (?:connect|discuss|talk))\b", re.I)
CREATOR_REPLY = re.compile(r"\b(?:interested|i(?:'d| would) love to|count me in|dm(?:'d|ed)? you|"
                           r"sent you a (?:dm|message|request)|check your (?:dm|inbox)|my (?:profile|portfolio|work)|"
                           r"i create|i(?:'m| am) an? (?:\w+ ){0,3}(?:creator|influencer))\b", re.I)


def commenter_type(name: str, headline: str, is_company: bool, comment: str = "", asked: list[str] = ()) -> str:
    """"Agency", "Creator" or "" (neither, e.g. a friend congratulating).

    Logged-out pages often hide commenters' headlines, so what they say counts too, read against what
    the post asked for (someone replying "Interested!" to a call for creators is a creator).
    """
    company = company_from_headline(headline)
    if is_company:
        return "Agency" if (looks_like_agency(name) or AGENCY_OFFER.search(comment)) else ""
    if headline:
        if re.search(r"(?<!ex-)(?<!ex )\bagenc(?:y|ies)\b", headline, re.I) or \
                (company and looks_like_agency(company)):
            return "Agency"
        if CREATOR_WORDS.search(headline):
            return "Creator"
    vendor_ask = any(w in a.lower() for a in asked for w in ("agency", "pitch", "vendor"))
    if VENDOR_PITCH.search(comment):  # "we at X ...", "we have a database of creators": a business pitching
        return "Agency"
    # a bare tag ("Navneet Kaur | Biggbell.com") refers someone else; contact details only count with an offer
    offers_contact = CONTACT.search(comment) and re.search(r"\b(?:connect|contact|reach|call|dm|whatsapp|mail|write)\b",
                                                            comment, re.I)
    if vendor_ask and (AGENCY_OFFER.search(comment) or offers_contact):
        return "Agency"
    if CREATOR_REPLY.search(comment) and set(asked) & {"Creators / influencers", "LinkedIn influencers/creators"}:
        return "Creator"
    if re.search(r"\b(?:i(?:'m| am) an? (?:\w+ ){0,3}(?:creator|influencer))\b", comment, re.I):
        return "Creator"
    return ""


def reddit_commenter_type(comment: str) -> str:
    """Reddit has no headlines, so judge by what the commenter says about themselves."""
    if re.search(r"\b(?:my|our) (?:agency|firm)\b|\bwe(?:'re| are) an? [^.]{0,40}agency\b|"
                 r"\bwe (?:run|help|work with) [^.]{0,40}(?:brands|creators|influencers|campaigns)\b", comment, re.I):
        return "Agency"
    if re.search(r"\b(?:i(?:'m| am) an? [^.]{0,30}(?:creator|influencer|youtuber|instagrammer|blogger)|"
                 r"my (?:channel|audience|followers|page)|i create (?:content|videos|ugc))\b", comment, re.I):
        return "Creator"
    return ""


# --- news and trade press: agency pitches and mandates -------------------------------------------
PITCH = re.compile(r"(?:calls? for|invites?|issues?|opens?|kicks? off|initiates?|floats?)"
                   r"[^.!?\n]{0,40}(?:pitch(?:es)?|rfps?|proposals?|mandates?)|"
                   r"(?:seeks?|seeking|looking for|on the hunt for|scouting for|hunts? for)"
                   r"[^.!?\n]{0,40}(?:agenc(?:y|ies)|partners?)\b", re.I)
BRAND_BEFORE = re.compile(r"^(.{2,60}?)\s+(?:(?:is|are)\s+)?(?:calls?|invites?|issues?|opens?|kicks? off|initiates?|"
                          r"floats?|announces?|seeks?|seeking|looking|on the hunt|scouting|hunts?|launch(?:es|ed)?|"
                          r"rolls? out|unveils?|debuts?|introduces?|appoints?|ropes? in|onboards?|hires?|names?|"
                          r"picks?|selects?|awards?|partners?|teams? up|collaborates?)\b", re.I)
NOT_A_BRAND = re.compile(r"^(?:brands?|why|how|what|when|these|this|the|a|an|top|\d+|marketers?|companies|startups?|"
                         r"agencies|ceos?|cmos?)\b", re.I)


def news_wants(title: str, snippet: str = "") -> list[str]:
    blob = f"{title}. {snippet}"
    found = wants(blob)
    if not found and PITCH.search(blob):
        found = ["Agency pitch / mandate"]
    return found


def brand_from_title(title: str) -> str:
    """'Exclusive: Bisleri calls for creative pitch' -> 'Bisleri'; '' if no clear brand name."""
    title = re.sub(r"^[^:]{1,25}:\s+", "", title or "")  # "Exclusive: ", "Pitch alert: "
    m = BRAND_BEFORE.search(title)
    if not m:
        return ""
    brand = m.group(1).strip(" :-–|\"'")
    if NOT_A_BRAND.search(brand) or len(brand.split()) > 6:
        return ""
    return brand


# --- brands already doing influencer marketing (campaigns, agency appointments) ------------------
CAMPAIGN = re.compile(
    r"(?:launch(?:es|ed|ing)?|roll(?:s|ed)? out|unveil(?:s|ed)?|kick(?:s|ed)? off|debut(?:s|ed)?|introduc(?:es|ed))"
    r"[^.!?\n]{0,50}(?:influencer|creator|ugc)[- ](?:led |driven |first )?(?:campaign|program(?:me)?|series|collab)|"
    r"(?:influencer|creator)[- ](?:led|driven|first) campaign|"
    r"(?:appoints?|appointed|ropes? in|roped in|onboards?|onboarded|hires?|hired|names?|picks?|selects?|awards?)"
    r"[^.!?\n]{0,50}(?:influencer|creator|social media|digital)[^.!?\n]{0,20}(?:agency|mandate|partner)|"
    r"(?:partners?|partnered|teams? up|teamed up|collaborates?|collaborated) with [^.!?\n]{0,30}"
    r"(?:\d+\+? )?(?:influencers|creators|content creators)\b", re.I)


def campaign_signal(text: str) -> str:
    """'Running influencer campaign' / 'Appointed an agency' if the text says the brand is doing
    influencer or creator marketing right now; '' otherwise."""
    m = CAMPAIGN.search(text or "")
    if not m:
        return ""
    return "Appointed an agency" if re.search(r"agency|mandate", m.group(0), re.I) else "Running influencer campaign"


# --- marketing hiring (a broader signal: the company is investing in marketing) ------------------
MARKETING_JOB_TITLE = re.compile(r"social media|digital marketing|brand manager|brand marketing|content marketing|"
                                 r"performance marketing|growth marketing|marketing manager|head of marketing|"
                                 r"marketing lead|cmo|chief marketing|community manager|partnerships? manager", re.I)


def pitch_details(comment: str) -> tuple[str, str]:
    """(company named in a pitch, public contact left in it): "we at TrendCore Media have ..." -> "TrendCore Media"."""
    m = re.search(r"\b(?:we at|here at|at|from|with)\s+@?([A-Z][\w&'\-]*(?:\.(?:com|in|io|ai|co))?"
                  r"(?:[ \t]+[A-Z][\w&'\-]*){0,3})", comment or "")
    company = m.group(1).strip(" .,'") if m else ""
    contacts = list(dict.fromkeys(c.strip() for c in CONTACT.findall(comment or "")))
    return company, ", ".join(contacts[:3])


# Comments by our own team are skipped (set ANCHORS_TEAM to a regex of names/companies to skip).
import os  # noqa: E402
OWN_TEAM = re.compile(os.environ.get("OWN_TEAM", r"\banchors?\b|@anchors|anchors\.in"), re.I)
