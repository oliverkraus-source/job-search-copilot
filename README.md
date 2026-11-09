# Job Search Copilot

**Finds and ranks job openings, analyses the fit, drafts application letters checked against your CV, and
tracks every application. You review and send each one yourself.**

![CI](https://github.com/oliverkraus-source/job-search-copilot/actions/workflows/ci.yml/badge.svg)

```
fetch ──► filter & rank ──► shortlist ──► match (AI) ──► draft (AI) ──► you review & send ──► track
 APIs       free, rules        you          fit score     CV-checked                           funnel
```

## Why it stops before "send"

Automating the last click would be easy, and a bad idea:

- Major job sites prohibit automated applications in their terms, and accounts get blocked.
- Recruiters recognise mass-sent applications. The letter is where a candidate shows motivation, so a
  human should read every one before it goes out under their name.

So the copilot automates the tedious 90% (finding, filtering, analysing, drafting, tracking) and leaves the
decision to the person.

## What it does

| Step | Command | Cost |
|---|---|---|
| **Fetch** jobs from public job-board APIs ([Arbeitnow](https://www.arbeitnow.com), [Remotive](https://remotive.com)), at most every 6 hours per source | `fetch` | free |
| **Add** an ad you found yourself (Jobbörse, company website, email) from a `.txt`, `.md` or `.pdf` | `add ad.txt --company ... --url ...` | free |
| **Filter and rank** with transparent rules: an IT role word in the title is required, entry-level words and remote add points, seniority and "5+ years" are excluded, remote jobs restricted to other regions are dropped. Every score shows its reasons. | `list`, `show ID` | free |
| **Shortlist** or skip | `shortlist ID`, `skip ID` | free |
| **Match**: runs the [Job-Match Agent](https://github.com/oliverkraus-source/job-match-agent) for a fit score and a gap analysis with verified CV evidence | `match ID` | ~$0.14 |
| **Draft** a tailored letter in the ad's language. **Every claim about the candidate comes with a word-for-word CV quote that code verifies.** An invented claim triggers one correction round; if it's still wrong, the letter is saved with a visible warning. | `draft ID` | ~$0.05 |
| **Open** the job page and the letter so you can send it yourself | `open ID` | free |
| **Track** sent / interview / offer / rejected, see your funnel, export to CSV | `mark ID sent`, `stats`, `export` | free |

## Setup

```bash
git clone https://github.com/oliverkraus-source/job-search-copilot.git
cd job-search-copilot
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy config.example.toml config.toml   # macOS/Linux: cp
```

Edit `config.toml` (your name, the path to your CV, and your search keywords) and set `ANTHROPIC_API_KEY`
for the AI steps. `config.toml`, your CV folder, the database and generated letters are git-ignored.

```bash
python -m jobcopilot fetch
python -m jobcopilot list
python -m jobcopilot show d18b08
python -m jobcopilot shortlist d18b08
python -m jobcopilot match d18b08
python -m jobcopilot draft d18b08
python -m jobcopilot open d18b08
python -m jobcopilot mark d18b08 sent
python -m jobcopilot stats
```

## Design notes

- **Rules before AI.** The free keyword filter cut 912 fetched jobs to 47 relevant ones in the first real
  run. Only jobs you shortlist go to the paid AI steps, so a job search costs cents, not dollars.
- **The model judges, code checks facts.** The same principle as the Job-Match Agent: letters come back as
  structured output (`messages.parse` with a Pydantic model) listing each claim and its CV quote, and the
  quotes are checked against the CV. The correction round is append-only: the model's first answer stays in
  the conversation and a follow-up message names the quotes that failed.
- **Polite API use.** Only sources with documented public APIs, a descriptive User-Agent, a minimum interval
  between fetches, and job links that point back to the source.
- **Local first.** One SQLite file. Re-fetching never duplicates jobs or overwrites the status you set.

## Tests

```bash
pytest     # 15 tests, no network or API key needed
```

The letter tests run the real Anthropic SDK against a scripted fake API, covering an invented quote that gets
corrected and one that stays wrong and is flagged. The CLI test runs the whole workflow (fetch, filter,
shortlist, draft, mark, stats, export) on fixture data.

## Limitations

- Keyword rules are blunt. They need tuning per person, and good jobs with unusual titles can be missed.
  `list --all` shows what was excluded and why.
- The verified-quote check proves a claim is *grounded* in the CV, not that the wording is fair. Read
  every letter before sending.
- The Bundesagentur für Arbeit job search isn't integrated: its public endpoint rejected documented
  requests. Use `add` for ads from the Jobbörse.
