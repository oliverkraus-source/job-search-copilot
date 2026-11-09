import httpx

from jobcopilot import sources
from jobcopilot.relevance import score
from jobcopilot.store import Job

ARBEITNOW_PAGE = {"data": [{
    "slug": "it-support-1st-level-acme-123", "company_name": "Acme GmbH", "title": " IT-Support 1st Level (m/w/d) ",
    "description": "<p>Wir suchen <b>Quereinsteiger</b>&nbsp;f&uuml;r unseren Helpdesk.</p><ul><li>Tickets</li></ul>",
    "remote": True, "url": "https://www.arbeitnow.com/jobs/acme/it-support", "tags": ["IT"],
    "job_types": ["full time"], "location": "Mainz", "created_at": 1793000000,
}]}
REMOTIVE = {"jobs": [
    {"id": 1, "url": "https://remotive.com/remote-jobs/1", "title": "Helpdesk Agent", "company_name": "Globex",
     "candidate_required_location": "USA Only", "description": "<p>Support</p>", "tags": [],
     "publication_date": "2026-11-01T10:00:00"},
    {"id": 2, "url": "https://remotive.com/remote-jobs/2", "title": "Junior Helpdesk Agent", "company_name": "Initech",
     "candidate_required_location": "Europe", "description": "<p>English support</p>", "tags": ["support"],
     "publication_date": "2026-11-02T10:00:00"},
]}


def mock_client(routes):
    def handler(request):
        if "arbeitnow" in request.url.host:
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=routes["arbeitnow"] if page == 1 else {"data": []})
        return httpx.Response(200, json=routes["remotive"])
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_arbeitnow_is_parsed_and_html_cleaned():
    jobs = sources.fetch_arbeitnow(mock_client({"arbeitnow": ARBEITNOW_PAGE}), pages=3)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "arbeitnow:it-support-1st-level-acme-123" and job.title == "IT-Support 1st Level (m/w/d)"
    assert job.remote and job.location == "Mainz" and job.posted_at.startswith("2026")
    assert "Quereinsteiger für unseren Helpdesk." in job.description and "- Tickets" in job.description


def test_list_items_wrapped_in_paragraphs_stay_on_one_line():
    assert sources.html_to_text("<ul><li><p>Tickets</p></li><li><p>Hardware</p></li></ul>") == "- Tickets\n- Hardware"


def test_remotive_jobs_are_marked_remote():
    jobs = sources.fetch_remotive(mock_client({"remotive": REMOTIVE}), categories=("customer-support",))
    assert [j.id for j in jobs] == ["remotive:1", "remotive:2"] and all(j.remote for j in jobs)


def test_manual_job_uses_first_line_as_title(tmp_path):
    ad = tmp_path / "stadt-mainz.txt"
    ad.write_text("\n# Ausbildung Fachinformatiker Systemintegration 2027\nStadt Mainz sucht ...", encoding="utf-8")
    job = sources.load_manual(ad, company="Stadt Mainz")
    assert job.id == "manual:stadt-mainz" and job.title == "Ausbildung Fachinformatiker Systemintegration 2027"


def make(title, description="", remote=False, source="arbeitnow", location=""):
    return Job(id=f"{source}:{title}", source=source, title=title, company="X", description=description,
               remote=remote, location=location)


def test_role_word_in_title_is_required(cfg):
    value, reasons = score(make("Junior PR Berater", "English, Deutsch"), cfg)
    assert value is None and "no IT role word" in reasons[0]


def test_level_text_and_remote_bonuses_add_up(cfg):
    value, reasons = score(make("Junior IT-Support (m/w/d)", "Quereinsteiger welcome, English", remote=True), cfg)
    assert value == 3 + 2 + 2 + 1
    assert any("level: junior" in r for r in reasons)


def test_exclusions_win(cfg):
    assert score(make("Sr. Developer"), cfg)[0] is None
    assert score(make("Business Developer"), cfg)[0] is None
    assert score(make("Developer", "You have 5+ years of experience"), cfg)[0] is None


def test_remote_region_filter_drops_us_only_jobs(cfg):
    assert score(make("Helpdesk Agent", remote=True, source="remotive", location="USA Only"), cfg)[0] is None
    assert score(make("Helpdesk Agent", remote=True, source="remotive", location="Europe"), cfg)[0] > 0


def test_remote_only_needs_the_remote_flag_or_a_nearby_location(cfg):
    cfg.remote_only = True
    cfg.nearby_locations = ["mainz"]
    perk_only = make("IT-Support", "mobiles Arbeiten und Homeoffice möglich", location="Berlin")
    assert score(perk_only, cfg)[0] is None                       # a perk in the text is not "remote"
    assert score(make("IT-Support", location="Mainz"), cfg)[0] > 0
    assert score(make("IT-Support", remote=True, location="Berlin"), cfg)[0] > 0
    assert score(make("IT-Support", source="manual", location="Berlin"), cfg)[0] > 0
