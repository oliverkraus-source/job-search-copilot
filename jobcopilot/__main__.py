"""Command-line interface.

  python -m jobcopilot fetch                 get new jobs from the job-board APIs
  python -m jobcopilot add ad.txt --company "Stadt Mainz" --url https://...
  python -m jobcopilot list                  ranked list of relevant jobs
  python -m jobcopilot show a1b2c3           details and why it was ranked
  python -m jobcopilot shortlist a1b2c3      mark as interesting (or: skip a1b2c3)
  python -m jobcopilot match a1b2c3          AI fit analysis (Job-Match Agent)
  python -m jobcopilot draft a1b2c3          AI application letter, checked against your CV
  python -m jobcopilot open a1b2c3           open the job page and the letter, to send it yourself
  python -m jobcopilot mark a1b2c3 sent      track: sent / interview / offer / rejected
  python -m jobcopilot stats                 your application funnel
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import webbrowser
from pathlib import Path

import httpx

from . import sources
from .config import Config, load_config
from .relevance import score
from .store import STATUSES, Job, Store

MIN_FETCH_INTERVAL_H = 6


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "job"


def rescore(store: Store, cfg: Config) -> None:
    for job in store.all():
        value, reasons = score(job, cfg)
        store.set_relevance(job.id, value if value is not None else -1, reasons)


def cmd_fetch(store: Store, cfg: Config, args) -> int:
    fetchers = {"arbeitnow": sources.fetch_arbeitnow, "remotive": sources.fetch_remotive}
    chosen = fetchers if args.source == "all" else {args.source: fetchers[args.source]}
    for name, fetch in chosen.items():
        last = float(store.get_meta(f"fetched:{name}") or 0)
        hours = (time.time() - last) / 3600
        if hours < MIN_FETCH_INTERVAL_H and not args.force:
            print(f"{name}: fetched {hours:.1f} h ago, skipping (be kind to free APIs; --force to override)")
            continue
        try:
            jobs = fetch()
        except httpx.HTTPError as exc:
            print(f"{name}: failed ({exc})")
            continue
        new = sum(store.upsert(j) for j in jobs)
        store.set_meta(f"fetched:{name}", str(time.time()))
        print(f"{name}: {len(jobs)} jobs, {new} new")
    rescore(store, cfg)
    relevant = [j for j in store.all() if (j.relevance or -1) > 0]
    print(f"\n{len(relevant)} relevant jobs in total. Run `list` to see them.")
    return 0


def cmd_add(store: Store, cfg: Config, args) -> int:
    job = sources.load_manual(args.file, title=args.title, company=args.company, url=args.url or "",
                              location=args.location or "", remote=args.remote)
    store.upsert(job)
    rescore(store, cfg)
    print(f"Added {job.short_id}: {job.title} ({job.company})")
    return 0


def _row(job: Job) -> str:
    where = "remote" if job.remote else (job.location or "-")
    rel = "-" if job.relevance is None or job.relevance < 0 else f"{job.relevance:g}"
    fit = f"{job.match_score}" if job.match_score is not None else ""
    return (f"{job.short_id}  {rel:>3}  {fit:>3}  {job.status:<11}  {_cut(job.title, 40)}  "
            f"{_cut(job.company, 18)}  {_cut(where, 14).rstrip()}")


def _cut(text: str, width: int) -> str:
    """Fit text into a fixed-width column (the list must fit a normal terminal window)."""
    text = " ".join(text.split())
    return (text[: width - 1] + "…" if len(text) > width else text).ljust(width)


def cmd_list(store: Store, cfg: Config, args) -> int:
    rescore(store, cfg)
    jobs = store.all(args.status)
    if not args.all:
        jobs = [j for j in jobs if (j.relevance or -1) > 0 or j.source == "manual"]
    if not args.status:
        jobs = [j for j in jobs if j.status != "skipped"]
    print(f"{'id':<6}  {'rel':>3}  {'fit':>3}  {'status':<11}  {'title':<40}  {'company':<18}  where")
    for job in jobs[: args.limit]:
        print(_row(job))
    print(f"\n{len(jobs)} job(s). rel = keyword relevance (free), fit = AI match score (after `match`).\n"
          "Details and source: python -m jobcopilot show <id>")
    return 0


def cmd_show(store: Store, cfg: Config, args) -> int:
    job = store.get(args.id)
    print(f"{job.title}\n{job.company} · {'remote' if job.remote else job.location} · {job.source} · "
          f"posted {job.posted_at}\n{job.url}\n\nStatus: {job.status}   Relevance: {job.relevance}   "
          f"Fit: {job.match_score}\nWhy: {'; '.join(job.relevance_reasons)}\n")
    print(job.description[:2500] + ("\n[...]" if len(job.description) > 2500 else ""))
    return 0


def cmd_status(store: Store, cfg: Config, args) -> int:
    for handle in args.ids:
        job = store.get(handle)
        store.set_status(job.id, args.status)
        print(f"{job.short_id}: {job.title} -> {args.status}")
    return 0


def _letters_dir(cfg: Config) -> Path:
    cfg.letters_dir.mkdir(parents=True, exist_ok=True)
    return cfg.letters_dir


def cmd_match(store: Store, cfg: Config, args) -> int:
    from jobmatch.agent import AgentError, run_agent
    from jobmatch.report import render_markdown

    job = store.get(args.id)
    print(f"Analysing fit for: {job.title} ({job.company}) with {args.model or cfg.model} ...")
    try:
        result = run_agent(f"{job.title}\n{job.company}\n\n{job.description}", cfg.cv_text(),
                           model=args.model or cfg.model)
    except AgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = _letters_dir(cfg) / f"{job.short_id}-{_slug(job.company)}-match.md"
    path.write_text(render_markdown(result, title=f"{job.title} — {job.company}"), encoding="utf-8")
    fit = result.session.match_score()["score"]
    store.set_match_score(job.id, fit)
    if job.status in ("new", "shortlisted"):
        store.set_status(job.id, "matched")
    cost = f"${result.cost_usd:.3f}" if result.cost_usd is not None else "unknown"
    print(f"Fit: {fit}/100. Report: {path}  (cost {cost})")
    return 0


def cmd_draft(store: Store, cfg: Config, args) -> int:
    from .letters import draft_letter, render_letter

    job = store.get(args.id)
    match_file = _letters_dir(cfg) / f"{job.short_id}-{_slug(job.company)}-match.md"
    notes = match_file.read_text(encoding="utf-8") if match_file.exists() else ""
    print(f"Drafting letter for: {job.title} ({job.company}) ...")
    try:
        result = draft_letter(job, cfg.cv_text(), name=cfg.name, portfolio_url=cfg.portfolio_url,
                              match_notes=notes, model=args.model or cfg.model)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = _letters_dir(cfg) / f"{job.short_id}-{_slug(job.company)}-letter.md"
    path.write_text(render_letter(job, result), encoding="utf-8")
    store.set_status(job.id, "drafted")
    ok = len(result.draft.claims) - len(result.unverified)
    print(f"Letter: {path}\n{ok}/{len(result.draft.claims)} claims verified against your CV"
          + ("  ⚠️ check the flagged ones!" if result.unverified else ""))
    return 0


def cmd_open(store: Store, cfg: Config, args) -> int:
    job = store.get(args.id)
    letter = _letters_dir(cfg) / f"{job.short_id}-{_slug(job.company)}-letter.md"
    if job.url:
        webbrowser.open(job.url)
    if letter.exists():
        webbrowser.open(letter.resolve().as_uri())
    print(f"Opened the job page{' and your letter' if letter.exists() else ''}.\n"
          f"Read the letter, adjust it, and send the application yourself. Then run: "
          f"python -m jobcopilot mark {job.short_id} sent")
    return 0


def cmd_stats(store: Store, cfg: Config, args) -> int:
    counts = store.counts()
    for status in STATUSES:
        if counts.get(status):
            print(f"{status:<12} {counts[status]:>4}")
    sent = sum(counts.get(s, 0) for s in ("sent", "interview", "offer", "rejected"))
    if sent:
        print(f"\nInterview rate: {(counts.get('interview', 0) + counts.get('offer', 0)) / sent:.0%} of {sent} sent")
    return 0


def cmd_export(store: Store, cfg: Config, args) -> int:
    with open(args.file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "status", "title", "company", "location", "remote", "relevance", "fit", "url", "source"])
        for j in store.all():
            writer.writerow([j.short_id, j.status, j.title, j.company, j.location, j.remote, j.relevance,
                             j.match_score, j.url, j.source])
    print(f"Exported to {args.file}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jobcopilot", description="Your job search copilot. You stay the pilot.")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="get new jobs from the job-board APIs")
    f.add_argument("--source", choices=["all", "arbeitnow", "remotive"], default="all")
    f.add_argument("--force", action="store_true")

    a = sub.add_parser("add", help="add a job ad you saved yourself (.txt, .md or .pdf)")
    a.add_argument("file")
    a.add_argument("--title")
    a.add_argument("--company")
    a.add_argument("--url")
    a.add_argument("--location")
    a.add_argument("--remote", action="store_true")

    ls = sub.add_parser("list", help="ranked list of relevant jobs")
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--all", action="store_true", help="include jobs the filter excluded")
    ls.add_argument("--limit", type=int, default=30)

    sub.add_parser("show", help="details of one job").add_argument("id")
    for name, status in (("shortlist", "shortlisted"), ("skip", "skipped")):
        sp = sub.add_parser(name, help=f"mark job(s) as {status}")
        sp.add_argument("ids", nargs="+")
        sp.set_defaults(status=status)
    m = sub.add_parser("mark", help="set a job's status, e.g. sent / interview / rejected")
    m.add_argument("ids", nargs=1)
    m.add_argument("status", choices=STATUSES)

    for name in ("match", "draft"):
        sp = sub.add_parser(name, help="AI fit analysis" if name == "match" else "AI application letter")
        sp.add_argument("id")
        sp.add_argument("--model")
    sub.add_parser("open", help="open job page and letter to send it yourself").add_argument("id")
    sub.add_parser("stats", help="application funnel")
    sub.add_parser("export", help="export all jobs to CSV").add_argument("file")
    return p


COMMANDS = {"fetch": cmd_fetch, "add": cmd_add, "list": cmd_list, "show": cmd_show, "shortlist": cmd_status,
            "skip": cmd_status, "mark": cmd_status, "match": cmd_match, "draft": cmd_draft, "open": cmd_open,
            "stats": cmd_stats, "export": cmd_export}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        store = Store(cfg.db_path)
        return COMMANDS[args.command](store, cfg, args)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
