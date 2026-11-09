"""SQLite storage: every job the copilot has seen, its status and history.

One local file (data/jobs.db), no server. Re-fetching never duplicates a job and
never overwrites the status you gave it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

STATUSES = ["new", "shortlisted", "matched", "drafted", "sent", "interview", "offer", "rejected", "skipped"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,            -- "<source>:<id at the source>"
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    remote INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    posted_at TEXT NOT NULL DEFAULT '',
    relevance REAL,
    relevance_reasons TEXT NOT NULL DEFAULT '[]',
    match_score INTEGER,
    status TEXT NOT NULL DEFAULT 'new',
    first_seen REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS history (job_id TEXT NOT NULL, status TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class Job:
    id: str
    source: str
    title: str
    company: str
    location: str = ""
    remote: bool = False
    url: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    posted_at: str = ""
    relevance: float | None = None
    relevance_reasons: list[str] = field(default_factory=list)
    match_score: int | None = None
    status: str = "new"

    @property
    def short_id(self) -> str:
        """Short, stable handle for the command line."""
        import hashlib
        return hashlib.sha1(self.id.encode()).hexdigest()[:6]


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    # ------------------------------------------------------------- jobs
    def upsert(self, job: Job) -> bool:
        """Insert a new job, or refresh an existing one's text. Returns True if it was new."""
        now = time.time()
        exists = self.db.execute("SELECT 1 FROM jobs WHERE id = ?", (job.id,)).fetchone()
        if exists:
            self.db.execute(
                "UPDATE jobs SET title=?, company=?, location=?, remote=?, url=?, description=?, tags=?, posted_at=? "
                "WHERE id=?",
                (job.title, job.company, job.location, int(job.remote), job.url, job.description,
                 json.dumps(job.tags), job.posted_at, job.id))
        else:
            self.db.execute(
                "INSERT INTO jobs (id, source, title, company, location, remote, url, description, tags, posted_at, "
                "status, first_seen, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job.id, job.source, job.title, job.company, job.location, int(job.remote), job.url,
                 job.description, json.dumps(job.tags), job.posted_at, "new", now, now))
            self.db.execute("INSERT INTO history VALUES (?,?,?)", (job.id, "new", now))
        self.db.commit()
        return not exists

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"], source=row["source"], title=row["title"], company=row["company"],
            location=row["location"], remote=bool(row["remote"]), url=row["url"], description=row["description"],
            tags=json.loads(row["tags"]), posted_at=row["posted_at"], relevance=row["relevance"],
            relevance_reasons=json.loads(row["relevance_reasons"]), match_score=row["match_score"],
            status=row["status"],
        )

    def all(self, status: str | None = None) -> list[Job]:
        sql, args = "SELECT * FROM jobs", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        rows = self.db.execute(sql + " ORDER BY relevance DESC NULLS LAST, first_seen DESC", args).fetchall()
        return [self._row_to_job(r) for r in rows]

    def get(self, handle: str) -> Job:
        """Find a job by its short id (or full id)."""
        matches = [j for j in self.all() if j.short_id.startswith(handle) or j.id == handle]
        if not matches:
            raise KeyError(f"No job with id '{handle}'. Run `list` to see ids.")
        if len(matches) > 1:
            raise KeyError(f"'{handle}' matches several jobs; use more characters.")
        return matches[0]

    def set_relevance(self, job_id: str, score: float, reasons: list[str]) -> None:
        self.db.execute("UPDATE jobs SET relevance=?, relevance_reasons=? WHERE id=?",
                        (score, json.dumps(reasons), job_id))
        self.db.commit()

    def set_match_score(self, job_id: str, score: int) -> None:
        self.db.execute("UPDATE jobs SET match_score=? WHERE id=?", (score, job_id))
        self.db.commit()

    def set_status(self, job_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"Unknown status '{status}'. Use one of: {', '.join(STATUSES)}")
        now = time.time()
        self.db.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, now, job_id))
        self.db.execute("INSERT INTO history VALUES (?,?,?)", (job_id, status, now))
        self.db.commit()

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ------------------------------------------------------------- meta (fetch timestamps)
    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value))
        self.db.commit()
