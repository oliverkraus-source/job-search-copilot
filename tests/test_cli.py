from jobcopilot import __main__ as cli
from jobcopilot import sources
from jobcopilot.letters import Claim, LetterDraft, LetterResult
from jobcopilot.store import Job

JOBS = [
    Job(id="arbeitnow:1", source="arbeitnow", title="Junior IT-Support (m/w/d)", company="Acme", remote=True,
        url="https://example.com/1", description="Quereinsteiger willkommen. Deutsch und English."),
    Job(id="arbeitnow:2", source="arbeitnow", title="Senior Developer", company="Globex"),
    Job(id="arbeitnow:3", source="arbeitnow", title="Marketing Manager", company="Initech"),
]


def run(cfg_path, *args):
    return cli.main(["--config", str(cfg_path), *args])


def test_full_workflow(cfg_path, monkeypatch, capsys):
    monkeypatch.setattr(sources, "fetch_arbeitnow", lambda: list(JOBS))
    monkeypatch.setattr(sources, "fetch_remotive", lambda: [])

    assert run(cfg_path, "fetch") == 0
    assert "arbeitnow: 3 jobs, 3 new" in capsys.readouterr().out

    # A second fetch right away is skipped to go easy on the free APIs.
    run(cfg_path, "fetch")
    assert "skipping" in capsys.readouterr().out

    run(cfg_path, "list")
    out = capsys.readouterr().out
    assert "Junior IT-Support" in out and "Senior Developer" not in out and "Marketing" not in out

    handle = JOBS[0].short_id
    run(cfg_path, "shortlist", handle)

    def fake_draft(job, cv_text, **kwargs):
        draft = LetterDraft(language="de", subject="Bewerbung", body="Sehr geehrte Damen und Herren, ...",
                            claims=[Claim(claim="languages", cv_quote="German (native), English (C1)")])
        return LetterResult(draft)

    monkeypatch.setattr("jobcopilot.letters.draft_letter", fake_draft)
    assert run(cfg_path, "draft", handle) == 0
    assert "1/1 claims verified" in capsys.readouterr().out
    letter = next((cfg_path.parent / "applications").glob(f"{handle}-*-letter.md"))
    assert "✅ languages" in letter.read_text(encoding="utf-8")

    run(cfg_path, "mark", handle, "sent")
    run(cfg_path, "mark", handle, "interview")
    capsys.readouterr()
    run(cfg_path, "stats")
    out = capsys.readouterr().out
    assert "interview" in out and "Interview rate: 100% of 1 sent" in out

    export = cfg_path.parent / "jobs.csv"
    run(cfg_path, "export", str(export))
    assert "Junior IT-Support" in export.read_text(encoding="utf-8")


def test_unknown_id_and_missing_config_give_clear_errors(cfg_path, tmp_path, capsys):
    assert run(cfg_path, "show", "nope00") == 1
    assert "No job with id" in capsys.readouterr().err
    assert cli.main(["--config", str(tmp_path / "missing.toml"), "list"]) == 1
    assert "Copy config.example.toml" in capsys.readouterr().err


def test_missing_cv_gives_a_helpful_error(cfg_path, monkeypatch, capsys):
    monkeypatch.setattr(sources, "fetch_arbeitnow", lambda: list(JOBS))
    monkeypatch.setattr(sources, "fetch_remotive", lambda: [])
    run(cfg_path, "fetch")
    (cfg_path.parent / "cv.md").unlink()
    assert run(cfg_path, "draft", JOBS[0].short_id) == 1
    assert "Your CV was not found" in capsys.readouterr().err
