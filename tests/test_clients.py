"""Backend clients against mocked HTTP (no server needed)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.backends import BackendError, DecideClient, SystemOneClient, make_jev_client

from .conftest import mock_http, run

# Request/response pair from the nimble /v1/systemone documentation example.
QUESTIONS = {
    "team": {"type": "choice", "instructions": "Which team should handle this ticket?",
             "positive": ["billing"],
             "criteria": {"billing": "Payments and refunds", "technical": "Bugs and integrations",
                          "other": "None of the above"}},
    "refund": {"type": "noul", "instructions": "Does the customer explicitly ask for a refund?",
               "min": 0.5},
    "urgency": {"type": "score", "instructions": "How urgent is this ticket?",
                "criteria": ["Routine", "Soon", "Urgent"]},
}
RESPONSE = {
    "model": "nimble",
    "answers": {
        "team": {"type": "choice", "choice": "billing",
                 "probabilities": {"billing": 0.985, "technical": 0.012, "other": 0.003},
                 "confidence": 0.922},
        "refund": {"type": "noul", "noul": 0.997},
        "urgency": {"type": "score", "score": 0.815,
                    "legend": {"0": "Routine", "1": "Soon", "2": "Urgent"},
                    "probabilities": {"0": 0.378, "1": 0.429, "2": 0.193}, "confidence": 0.046}},
    "usage": {"input_tokens": 841, "output_tokens": 4},
}
STATE = {"ticket": "I was charged twice. Please refund the extra payment."}


# --- systemone -----------------------------------------------------------------

def test_systemone_single_request_wire_format():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=RESPONSE)

    c = mock_http(SystemOneClient(base_url="http://h:11434/v1/", model="nimble",
                                  api_key="k"), handler)
    answers = run(c.ask(STATE, QUESTIONS))

    assert len(seen) == 1
    req = seen[0]
    assert req.url.path == "/v1/systemone"
    body = json.loads(req.content)
    assert body["model"] == "nimble" and body["state"] == STATE
    assert body["questions"]["refund"] == {"type": "noul", "instructions": QUESTIONS["refund"]["instructions"]}
    assert "positive" not in body["questions"]["team"]
    assert answers == RESPONSE["answers"]


def test_systemone_sends_api_key():
    c = SystemOneClient(base_url="http://h/v1", model="m", api_key="secret")
    assert c._http.headers["authorization"] == "Bearer secret"


def test_systemone_omits_model_when_unset():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=RESPONSE)

    run(mock_http(SystemOneClient(base_url="http://h/v1"), handler).ask(STATE, QUESTIONS))
    assert "model" not in seen[0]


def test_systemone_missing_answer_raises():
    partial = {"answers": {"team": RESPONSE["answers"]["team"]}}
    c = mock_http(SystemOneClient(base_url="http://h/v1"),
                  lambda req: httpx.Response(200, json=partial))
    with pytest.raises(BackendError, match="refund"):
        run(c.ask(STATE, QUESTIONS))


def test_systemone_http_error_raises():
    c = mock_http(SystemOneClient(base_url="http://h/v1"),
                  lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(BackendError, match="/systemone"):
        run(c.ask(STATE, QUESTIONS))


# --- decide adapter --------------------------------------------------------------

def _decide_handler(seen):
    def handler(req):
        b = json.loads(req.content)
        seen.append(b)
        if b["kind"] == "noul":
            return httpx.Response(200, json={"options": ["false", "true"],
                                             "probabilities": [0.2, 0.8]})
        n = len(b["options"])
        probs = [0.1] * (n - 1) + [round(1 - 0.1 * (n - 1), 6)]
        return httpx.Response(200, json={"options": b["options"], "probabilities": probs})
    return handler


def test_decide_converts_to_systemone_answers():
    seen = []
    c = mock_http(DecideClient(base_url="http://h:8000/v1"), _decide_handler(seen))
    a = run(c.ask(STATE, QUESTIONS))

    assert len(seen) == 3                                   # one request per question
    assert a["refund"] == {"type": "noul", "noul": 0.8}
    assert a["team"]["type"] == "choice" and a["team"]["choice"] == "other"
    assert set(a["team"]["probabilities"]) == {"billing", "technical", "other"}
    assert a["urgency"]["score"] == pytest.approx(0.1 * 1 + 0.8 * 2)
    assert a["urgency"]["legend"] == {"0": "Routine", "1": "Soon", "2": "Urgent"}


def test_decide_choice_options_carry_descriptions():
    seen = []
    run(mock_http(DecideClient(base_url="http://h/v1"), _decide_handler(seen))
        .ask(STATE, {"team": QUESTIONS["team"]}))
    assert seen[0]["options"][0] == "billing: Payments and refunds"
    assert seen[0]["question"] == QUESTIONS["team"]["instructions"]


# --- factory -------------------------------------------------------------------

def test_make_jev_client():
    assert isinstance(make_jev_client("systemone", base_url="http://h/v1"), SystemOneClient)
    assert isinstance(make_jev_client("decide", base_url="http://h/v1"), DecideClient)
    with pytest.raises(ValueError):
        make_jev_client("grpc", base_url="http://h/v1")
