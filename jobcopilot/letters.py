"""Draft a tailored application letter, and check every claim it makes against the CV.

The letter comes back as structured output: the text plus a list of claims about
the candidate, each with a word-for-word CV quote. Code checks every quote. If one
is not in the CV, the model gets one chance to fix the letter; if it still fails,
the letter is saved with a visible warning instead of silently passing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

import anthropic
from jobmatch.documents import normalize
from jobmatch.pricing import cost_usd
from pydantic import BaseModel, Field

from .store import Job

SYSTEM_PROMPT = """\
You write job application letters (German: Anschreiben) for one candidate, based on their CV \
and a job ad.

Rules:
- Write in the language of the job ad. German ads get a formal German letter ("Sie"). Address a \
contact person only if the ad names one; otherwise use "Sehr geehrte Damen und Herren," or \
"Dear Hiring Team,".
- 200-320 words for the body. No address block and no date: the candidate adds those.
- Be specific: connect 2-3 concrete tasks or requirements from the ad to the candidate's real \
experience. No generic phrases ("hiermit bewerbe ich mich", "I am writing to apply").
- Every factual statement about the candidate (jobs, training, skills, projects, numbers, \
languages) must come from the CV. List each one in `claims` with a word-for-word quote from the \
CV. Never invent experience, employers, degrees, numbers or certificates.
- Be honest about the career change and about gaps; show motivation and how the candidate is \
closing them. Do not assume the candidate's gender, age or background beyond the CV.
- If a portfolio URL is given, mention it once. End with the candidate's name."""


class Claim(BaseModel):
    claim: str = Field(description="A factual statement about the candidate made in the letter.")
    cv_quote: str = Field(description="Word-for-word quote from the CV that supports the claim.")


class LetterDraft(BaseModel):
    language: Literal["de", "en"]
    subject: str = Field(description="Subject line, e.g. 'Bewerbung als Fachinformatiker ... (Ausbildung 2027)'.")
    body: str = Field(description="The full letter, from greeting to signature.")
    claims: list[Claim]


@dataclass
class LetterResult:
    draft: LetterDraft
    unverified: list[Claim] = field(default_factory=list)
    attempts: int = 1
    cost_usd: float | None = 0.0


def unverified_claims(draft: LetterDraft, cv_text: str) -> list[Claim]:
    cv = normalize(cv_text)
    return [c for c in draft.claims if not c.cv_quote.strip() or normalize(c.cv_quote) not in cv]


def _job_block(job: Job) -> str:
    return (f"<job_ad>\nTitle: {job.title}\nCompany: {job.company}\nLocation: {job.location or '-'}"
            f"{' (remote)' if job.remote else ''}\n\n{job.description.strip()[:12000]}\n</job_ad>")


def draft_letter(job: Job, cv_text: str, *, name: str, portfolio_url: str = "", match_notes: str = "",
                 model: str = "claude-opus-5-5", client: anthropic.Anthropic | None = None) -> LetterResult:
    if client is None:
        if not any(os.environ.get(v) for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
            raise RuntimeError("Set ANTHROPIC_API_KEY to draft letters.")
        client = anthropic.Anthropic()

    user = (f"{_job_block(job)}\n\n<cv>\n{cv_text.strip()}\n</cv>\n\n"
            f"Candidate name: {name}\nPortfolio: {portfolio_url or '(none)'}\n")
    if match_notes:
        user += f"\n<fit_analysis>\n{match_notes.strip()}\n</fit_analysis>\n"
    user += "\nWrite the application letter."
    messages: list = [{"role": "user", "content": user}]

    total_cost: float | None = 0.0
    for attempt in (1, 2):
        response = client.beta.messages.parse(
            model=model, max_tokens=16000, system=SYSTEM_PROMPT, messages=messages,
            output_format=LetterDraft, output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        turn_cost = cost_usd(response.model, response.usage)
        total_cost = None if (turn_cost is None or total_cost is None) else total_cost + turn_cost
        if response.stop_reason == "refusal":
            raise RuntimeError("The model declined to write this letter.")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise RuntimeError("The letter was cut off or could not be parsed; try again.")
        draft = response.parsed_output
        bad = unverified_claims(draft, cv_text)
        if not bad or attempt == 2:
            return LetterResult(draft, bad, attempt, total_cost)
        # Append-only: keep the model's turn as it was, then explain what failed.
        messages.append({"role": "assistant", "content": response.content})
        listing = "\n".join(f'- "{c.cv_quote}" (claim: {c.claim})' for c in bad)
        messages.append({"role": "user", "content": (
            "These quotes are not word for word in the CV:\n" + listing +
            "\nRewrite the letter: fix each quote to match the CV exactly, or remove the claim from the letter."
        )})
    raise AssertionError("unreachable")


def render_letter(job: Job, result: LetterResult) -> str:
    d = result.draft
    lines = [f"<!-- {job.title} | {job.company} | {job.url} | source: {job.source} -->", "",
             f"**Subject:** {d.subject}", "", d.body.strip(), "", "---", "", "### Checked against your CV", ""]
    bad = {id(c) for c in result.unverified}
    for c in d.claims:
        mark = "⚠️ NOT FOUND IN CV" if id(c) in bad else "✅"
        lines.append(f'- {mark} {c.claim} — "{c.cv_quote}"')
    if result.unverified:
        lines += ["", "**⚠️ Some claims could not be verified. Fix or remove them before sending.**"]
    cost = f"${result.cost_usd:.3f}" if result.cost_usd is not None else "unknown"
    lines += ["", f"<sub>{result.attempts} attempt(s), estimated cost {cost}. Read it, edit it, then send it "
              "yourself.</sub>", ""]
    return "\n".join(lines)
