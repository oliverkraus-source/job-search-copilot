"""Free, transparent pre-filter: which jobs are worth a closer (paid) look?

Rule-based on purpose. It costs nothing, runs on hundreds of jobs in a
millisecond, and every score comes with the reasons behind it, so you can see
why a job was ranked high or thrown out.
"""

from __future__ import annotations

from jobmatch.skills import contains

from .config import Config
from .store import Job


def score(job: Job, cfg: Config) -> tuple[float | None, list[str]]:
    """Return (score, reasons). None means the job is excluded."""
    title = job.title.lower()
    text = f"{job.title}\n{job.description}".lower()
    reasons: list[str] = []

    for term in cfg.exclude_title:
        if contains(title, term):
            return None, [f"excluded: title contains '{term}'"]
    for term in cfg.exclude_text:
        if contains(text, term):
            return None, [f"excluded: ad mentions '{term}'"]

    # Location: a job counts as remote only if the job board marks it remote (a perk like
    # "mobiles Arbeiten" in the text is not enough). Other jobs must be in a nearby place.
    nearby = any(contains(job.location, place) for place in cfg.nearby_locations)
    if job.source != "manual" and not job.remote:
        if cfg.remote_only and not nearby:
            return None, [f"excluded: not remote and not nearby ({job.location or 'no location'})"]
        if nearby:
            reasons.append(f"nearby: {job.location}")
    if job.source == "remotive" and cfg.remote_regions:
        region = job.location.lower()
        if region and not any(r.lower() in region for r in cfg.remote_regions):
            return None, [f"excluded: remote only for '{job.location}'"]

    role_hits = [t for t in cfg.role_keywords if contains(title, t)]
    if not role_hits:
        return None, ["excluded: no IT role word in the title"]
    points = 3.0
    reasons.append(f"+3 role: {', '.join(role_hits[:3])}")
    level_hits = [t for t in cfg.level_keywords if contains(title, t)]
    if level_hits:
        points += 2
        reasons.append(f"+2 level: {', '.join(level_hits[:3])}")
    text_hits = [t for t in cfg.text_keywords if contains(text, t)]
    if text_hits:
        bonus = min(len(text_hits), 4)
        points += bonus
        reasons.append(f"+{bonus} ad mentions: {', '.join(text_hits[:6])}")
    if job.remote:
        points += 1
        reasons.append("+1 remote")
    return points, reasons
