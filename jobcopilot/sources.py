"""Where jobs come from: public job-board APIs, plus ads you save yourself.

Only sources that offer free, documented API access are used - no scraping of
sites whose terms forbid it. Each source is fetched at most every few hours
(Remotive asks API users to keep requests low and to credit them as the source).
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx

from .store import Job

USER_AGENT = "job-search-copilot/0.1 (personal job search tool; github.com/oliverkraus-source)"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw: str) -> str:
    parser = _TextExtractor()
    parser.feed(raw or "")
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"(?m)^- *\n\s*", "- ", text)          # <li><p>text</p></li> -> "- text"
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)


def fetch_arbeitnow(client: httpx.Client | None = None, pages: int = 3) -> list[Job]:
    """Arbeitnow's public job board API (mostly Germany, many English-language and remote jobs)."""
    client = client or _client()
    jobs: list[Job] = []
    for page in range(1, pages + 1):
        resp = client.get(ARBEITNOW_URL, params={"page": page})
        resp.raise_for_status()
        data = resp.json().get("data", [])
        for item in data:
            posted = datetime.fromtimestamp(item.get("created_at", 0), UTC).date().isoformat()
            jobs.append(Job(
                id=f"arbeitnow:{item['slug']}", source="arbeitnow", title=item["title"].strip(),
                company=item.get("company_name", "").strip(), location=item.get("location", "").strip(),
                remote=bool(item.get("remote")), url=item.get("url", ""),
                description=html_to_text(item.get("description", "")),
                tags=[*item.get("tags", []), *item.get("job_types", [])], posted_at=posted,
            ))
        if not data:
            break
    return jobs


def fetch_remotive(client: httpx.Client | None = None,
                   categories: tuple[str, ...] = ("customer-support", "software-dev")) -> list[Job]:
    """Remotive's public remote-jobs API. Job pages link back to Remotive, as their terms ask."""
    client = client or _client()
    jobs: list[Job] = []
    for category in categories:
        resp = client.get(REMOTIVE_URL, params={"category": category})
        resp.raise_for_status()
        for item in resp.json().get("jobs", []):
            jobs.append(Job(
                id=f"remotive:{item['id']}", source="remotive", title=item["title"].strip(),
                company=item.get("company_name", "").strip(),
                location=item.get("candidate_required_location", "").strip(), remote=True,
                url=item.get("url", ""), description=html_to_text(item.get("description", "")),
                tags=item.get("tags", []), posted_at=(item.get("publication_date") or "")[:10],
            ))
    return jobs


def load_manual(path: str | Path, title: str | None = None, company: str | None = None,
                url: str = "", location: str = "", remote: bool = False) -> Job:
    """A job ad you saved yourself (copied from the Jobbörse, a company site, an email...).

    Without --title/--company, the first non-empty line is used as the title.
    """
    from jobmatch.documents import load_text

    path = Path(path)
    text = load_text(path).strip()
    first_line = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), path.stem)
    return Job(
        id=f"manual:{path.stem}", source="manual", title=title or first_line[:120],
        company=company or "(unknown company)", location=location, remote=remote, url=url,
        description=text, posted_at=datetime.now(UTC).date().isoformat(),
    )
