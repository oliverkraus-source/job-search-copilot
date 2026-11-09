"""draft_letter runs through the real Anthropic SDK (beta parse) against a scripted fake API."""

import json

import anthropic
import httpx2

from jobcopilot.letters import LetterDraft, draft_letter, render_letter, unverified_claims
from jobcopilot.store import Job

from .conftest import CV

JOB = Job(id="manual:helpdesk", source="manual", title="IT-Support (m/w/d)", company="Acme",
          description="Wir suchen Unterstützung im Helpdesk. Gute Deutsch- und Englischkenntnisse.")


def letter(quotes):
    return {"language": "de", "subject": "Bewerbung als IT-Support",
            "body": "Sehr geehrte Damen und Herren,\n...\nSam Example",
            "claims": [{"claim": f"claim {i}", "cv_quote": q} for i, q in enumerate(quotes)]}


def reply(payload):
    return {"id": "msg", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(payload)}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 2000, "output_tokens": 800}}


def fake_client(replies):
    requests, it = [], iter(replies)

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=next(it))

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return anthropic.Anthropic(api_key="x", http_client=http), requests


def test_unverified_claims_detects_invented_quotes():
    draft = LetterDraft(**letter(["led a team of 12 warehouse employees per shift", "Certified Kubernetes admin"]))
    assert [c.cv_quote for c in unverified_claims(draft, CV)] == ["Certified Kubernetes admin"]


def test_invented_quote_triggers_one_correction_round():
    client, requests = fake_client([
        reply(letter(["German (native), English (C1)", "5 years of IT support"])),      # invented
        reply(letter(["German (native), English (C1)", "JavaScript, React, Git"])),     # fixed
    ])
    result = draft_letter(JOB, CV, name="Sam Example", client=client)
    assert result.attempts == 2 and result.unverified == []
    # The correction request keeps the first answer and names the failing quote.
    second = requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert "5 years of IT support" in second[-1]["content"]
    assert requests[0]["fallbacks"] == "default" and requests[0]["output_config"]["format"]["type"] == "json_schema"
    assert "✅" in render_letter(JOB, result) and "⚠️" not in render_letter(JOB, result)


def test_letter_that_stays_wrong_is_flagged_not_hidden():
    bad = reply(letter(["Fluent in Japanese"]))
    client, _ = fake_client([bad, bad])
    result = draft_letter(JOB, CV, name="Sam Example", client=client)
    assert len(result.unverified) == 1
    assert "Fix or remove them before sending" in render_letter(JOB, result)
