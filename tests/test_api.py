"""HTTP endpoints, run against FakeJev."""
from __future__ import annotations

from .conftest import API_KEY


# --- auth / health -------------------------------------------------------------

def test_health_needs_no_key(client):
    assert client.get("/health", headers={"X-API-Key": ""}).json() == {"status": "ok"}


def test_wrong_key_rejected(client):
    assert client.get("/v1/pipelines", headers={"X-API-Key": "nope"}).status_code == 401


def test_bearer_key_accepted(client):
    r = client.get("/v1/pipelines",
                   headers={"X-API-Key": "", "Authorization": f"Bearer {API_KEY}"})
    assert r.status_code == 200


# --- grant matching ------------------------------------------------------------

def test_match_ordered_by_probability(client):
    body = client.post("/v1/grants/match", json={"profile": "I design radio hardware"}).json()
    assert body["rank_by"] == "match"
    assert body["considered"] == 3
    probs = [m["probability"] for m in body["matches"]]
    assert probs == sorted(probs, reverse=True)
    top = body["matches"][0]
    assert top["grant_id"] == "example-rf-hardware" and top["probability"] == 0.9
    assert set(top["answers"]) == {"match", "eligibility", "no_conflict_of_interest"}
    assert top["gated_by"] == []


def test_match_one_backend_call_per_grant(client, fake_jev):
    client.post("/v1/grants/match", json={"profile": "x"})
    assert len(fake_jev.calls) == 3
    state, questions = fake_jev.calls[0]
    assert list(state) == ["applicant_profile", "grant"]   # profile first: prefix caching
    assert len(questions) == 3


def test_match_gate_drops_grant(client):
    client.app.state.services.config["matching"]["questions"]["eligibility"]["min"] = 0.5
    body = client.post("/v1/grants/match", json={"profile": "x",
                                                 "grant_ids": ["example-rf-hardware",
                                                               "example-ml-climate"]}).json()
    assert [m["grant_id"] for m in body["matches"]] == ["example-rf-hardware"]


def test_match_top_k(client):
    body = client.post("/v1/grants/match", json={"profile": "x", "top_k": 1}).json()
    assert len(body["matches"]) == 1


def test_match_inline_grants(client):
    body = client.post("/v1/grants/match", json={
        "profile": "x",
        "grants": [{"id": "b", "title": "Biology"}, {"id": "a", "title": "Radio"}]}).json()
    assert [m["grant_id"] for m in body["matches"]] == ["a", "b"]
    assert body["considered"] == 2


def test_match_unknown_grant_404(client):
    r = client.post("/v1/grants/match", json={"profile": "x", "grant_ids": ["nope"]})
    assert r.status_code == 404


def test_match_unknown_pipeline_404(client):
    r = client.post("/v1/grants/match", json={"profile": "x", "pipeline": "nope"})
    assert r.status_code == 404


def test_match_structured_profile(client):
    r = client.post("/v1/grants/match",
                    json={"profile": {"field": "RF engineering", "career_stage": "PhD"}})
    assert r.status_code == 200


# --- application alignment -----------------------------------------------------

def test_align(client):
    r = client.post("/v1/applications/align",
                    json={"application": "We build radios.", "grant_id": "example-rf-hardware"})
    assert r.status_code == 200, r.text
    a = r.json()["alignment"]
    assert a["grant_id"] == "example-rf-hardware"
    assert a["probability"] == 0.9
    assert a["answers"]["focus_coverage"]["score"] == 2.0


def test_align_requires_grant(client):
    assert client.post("/v1/applications/align", json={"application": "x"}).status_code == 422
    assert client.post("/v1/applications/align",
                       json={"application": "x", "grant_id": "nope"}).status_code == 404


# --- /v1/systemone passthrough -------------------------------------------------

def test_systemone_shape(client):
    r = client.post("/v1/systemone", json={
        "model": "ignored",
        "state": {"ticket": "radio is broken"},
        "questions": {
            "refund": {"type": "noul", "instructions": "Refund?"},
            "team": {"type": "choice", "instructions": "Team?",
                     "criteria": {"billing": "Payments", "other": None}},
            "urgency": {"type": "score", "instructions": "Urgency?",
                        "criteria": ["Routine", "Soon", "Urgent"]}}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "fake"
    assert body["answers"]["refund"] == {"type": "noul", "noul": 0.9}
    assert body["answers"]["urgency"]["legend"]["2"] == "Urgent"


def test_systemone_rejects_bad_question(client):
    for q in ({"type": "score", "instructions": "?", "criteria": ["one"]},
              {"type": "choice", "instructions": "?", "criteria": {"only": None}},
              {"type": "maybe", "instructions": "?"}):
        r = client.post("/v1/systemone", json={"state": "x", "questions": {"q": q}})
        assert r.status_code == 422, q


# --- introspection -------------------------------------------------------------

def test_listing_endpoints(client):
    assert set(client.get("/v1/pipelines").json()) == {"grant_match", "application_alignment"}
    steps = client.get("/v1/steps").json()
    assert {"jev_match_grants", "jev_alignment"} <= set(steps)
    assert "rank_by" in steps["jev_match_grants"]["params"]
    assert len(client.get("/v1/grants").json()) == 3


def test_generic_pipeline_run(client):
    r = client.post("/v1/pipelines/grant_match/run", json={"inputs": {"profile": "radio"}})
    assert r.status_code == 200 and r.json()["matches"]
