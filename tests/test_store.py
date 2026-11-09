import pytest

from jobcopilot.store import Job, Store


def test_refetch_keeps_status_and_does_not_duplicate(tmp_path):
    store = Store(tmp_path / "jobs.db")
    job = Job(id="arbeitnow:a", source="arbeitnow", title="Helpdesk", company="Acme")
    assert store.upsert(job) is True
    store.set_status(job.id, "sent")
    job.title = "Helpdesk (updated)"
    assert store.upsert(job) is False
    [saved] = store.all()
    assert saved.status == "sent" and saved.title == "Helpdesk (updated)"
    assert store.counts() == {"sent": 1}


def test_short_ids_and_errors(tmp_path):
    store = Store(tmp_path / "jobs.db")
    job = Job(id="manual:x", source="manual", title="T", company="C")
    store.upsert(job)
    assert store.get(job.short_id[:4]).id == "manual:x"
    with pytest.raises(KeyError):
        store.get("zzzzzz")
    with pytest.raises(ValueError):
        store.set_status(job.id, "hired-by-magic")
