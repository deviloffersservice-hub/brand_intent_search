# Brand intent search

Every 3 hours this finds **brands that want marketing help**:
- an influencer marketing agency;
- LinkedIn influencers or creators;
- creators on any platform;
- any marketing or LinkedIn marketing agency.

It keeps only brands in **India or the US**, plus brands anywhere that are marketing **in India**,
and only asks from the **last 14 days**. It also collects the **agencies and creators who reply**
in those posts' comments.

Results go to three tabs in
[this Google Sheet](https://docs.google.com/spreadsheets/d/1h3GY7aUPnDZrv1lfYOrG1Oc932SFM843Hb3PFID7Ya4/edit):

| Tab | One row per |
|---|---|
| `github script for brands` | brand ask: what they want, market, source, link, date, the matching text, and how many agencies and creators replied |
| `github script for agencies` | agency: from a comment on a brand post, a Reddit reply, or an agency's own post asking for creators |
| `github script for creators` | creator who replied to a brand post |

There are no duplicates. Brands are deduplicated by post or job link, with one job row per company.
Agencies and creators are deduplicated by profile.

It's free: no LinkedIn login, no paid APIs, and it runs on GitHub Actions in a public repo.

## Sources

| Source | How | What counts |
|---|---|---|
| LinkedIn posts | Web search (`site:linkedin.com/posts` plus phrases like "looking for an influencer marketing agency"), then the public post page | The post asks for an agency, creators or influencers. The poster isn't an agency advertising itself. The post is at most 14 days old (the date is in the link). |
| LinkedIn jobs | LinkedIn's public job search, in India and the US, for the last 14 days | Influencer, creator or LinkedIn-marketing roles at a company that isn't an agency or recruiter |
| Reddit | Web search (`site:reddit.com`), then Reddit's public JSON when it answers | Same asks as LinkedIn posts. If Reddit refuses cloud servers, the search title and snippet are used and the row says "(search snippet)". |
| News | News search | Brands calling agency pitches or mandates, or seeking an agency |

**Market rules:**
- The poster's LinkedIn country (`in.linkedin.com` is India, `www.linkedin.com` is US) or the job location decides first.
- Otherwise, any mention of India or an Indian city or currency marks the row "India market".

**Commenters:**
- **Agency:** a company page, or a person whose headline has an agency/marketing/media word plus a role (Founder, Director and so on).
- **Creator:** a headline with creator, influencer, UGC, Top Voice and so on.
- Everyone else (friends saying congrats) is ignored.

All rules are plain regular expressions in `brand_intent/intent.py`, so they're easy to tune.

## What to expect

These are measured on GitHub, October 2026:

- **LinkedIn jobs:** the first runs took in the last 14 days of postings, about 320 brands; about 2 in 3
  influencer-marketing job ads are from agencies or recruiters and are skipped. After that, each run adds
  only newly posted jobs: a handful to a couple of dozen.
- **LinkedIn posts:** the related-posts crawl reads up to 300 posts per run on the topic. Posts where a
  brand itself asks for an agency or creators are rare, about 1 in 300. Most posts on the topic are
  agencies and creators marketing themselves, and those are skipped.
- **News:** an agency pitch or mandate from time to time (for example ICC's 2027 Women's Champions
  Trophy marketing and PR mandate).
- **Reddit:** Reddit refuses GitHub's machines, and threads without a date are skipped. Expect little
  from it.
- **Agencies and creators:** these come from the comments on the brand posts above, so they're few.
  LinkedIn hides most commenters' headlines when you're logged out, so they're judged mostly by what
  they write.

Each run aims for `TARGET_BRANDS` (100) new genuine brands and **never pads**. The run log says how many
it found and how far short it was ("target 100, short by N"), plus a duplicate check of the sheet.

LinkedIn only shows "More relevant posts" on posts about 3+ days old. The crawl reads those first,
re-reads younger posts in a later run, and keeps its unread queue between runs in the Actions cache.

## Run it

- **Automatic:** `.github/workflows/brand-intent.yml` runs every 3 hours (:17, with :47 as a backup when GitHub drops the first).
- **By hand:** Actions → Brand intent search → Run workflow. Tick "dry run" to print results without writing.
- **Locally:**

  ```
  pip install -r requirements.txt
  GOOGLE_SERVICE_ACCOUNT_JSON="$(cat key.json)" python -m brand_intent.run          # writes to the sheet
  python -m brand_intent.run --dry-run                                               # prints only
  python -m pytest -q                                                                # offline tests
  ```

## Setup (one time)

1. Share the sheet with `brand-bot@brand-intent-118912.iam.gserviceaccount.com` as **Editor**.
2. Add the robot's JSON key as the repository secret `GOOGLE_SERVICE_ACCOUNT_JSON` (Settings → Secrets and variables → Actions).

The tabs are created automatically on the first run.

## Settings

Environment variables, defaults in `brand_intent/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `MAX_AGE_DAYS` | 14 | Oldest post, job or news item kept |
| `SEARCHES_PER_RUN` | 30 | Web searches per run, spaced `SEARCH_GAP_SECONDS` (20) apart |
| `MAX_POST_PAGES` | 150 | LinkedIn post pages read per run |
| `JOB_PAGES_PER_QUERY` | 2 | Pages of 10 jobs per keyword and country |

Search phrases rotate every run (`brand_intent/queries.py`), so over a day every phrase is used
without asking too much of the search engines at once.
