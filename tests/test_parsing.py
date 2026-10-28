from pathlib import Path

from brand_intent.linkedin import activity_time, parse_jobs, parse_post

FIX = Path(__file__).parent / "fixtures"
URL = "https://www.linkedin.com/posts/gavinmooney_this-is-what-progress-looks-like-and-is-activity-7457681396803985409-YkC0"


def test_post_author_date_text_and_comments():
    p = parse_post((FIX / "post.html").read_text(), URL)
    assert p.author.name == "Gavin Mooney" and p.author.kind == "in" and p.author.country == "au"
    assert p.author.headline.startswith("Energy Transition Advisor")
    assert p.published.year == 2026 and p.text.startswith("This is what progress looks like")
    assert len(p.comments) == 10
    c = p.comments[1]
    assert c.author.name == "Mike Thornton GAICD" and c.author.url.endswith("/in/mike-thornton-gaicd-063a691a")
    assert "repowering" in c.text


def test_jobs_cards():
    jobs = parse_jobs((FIX / "jobs.html").read_text())
    assert len(jobs) == 10
    j = jobs[0]
    assert j.url.startswith("https://www.linkedin.com/jobs/view/") and j.title and j.company
    assert j.company_url.startswith("https://www.linkedin.com/company/") and j.posted is not None


def test_activity_time():
    assert activity_time("7457681396803985409").year == 2026
    assert activity_time(None) is None
