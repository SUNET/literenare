"""Live tests against a real JeV server. Skipped unless JEV_LIVE_URL is set.

    JEV_LIVE_URL=http://localhost:11434/v1 JEV_LIVE_MODEL=nimble pytest tests/live -v

These check the wire contract and sanity of the answers, not exact numbers.
"""
from __future__ import annotations

import os

import pytest

from app.backends import make_jev_client
from app.pipeline import Context
from app.pipeline.steps.matching import jev_match_grants
from app.services import Services

from ..conftest import run
from ..test_clients import QUESTIONS, STATE

URL = os.environ.get("JEV_LIVE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set JEV_LIVE_URL to run live tests")


@pytest.fixture
def jev():
    return make_jev_client(os.environ.get("JEV_LIVE_PROTOCOL", "systemone"), base_url=URL,
                           model=os.environ.get("JEV_LIVE_MODEL", "nimble"), timeout=120)


def _is_prob(x):
    return isinstance(x, (int, float)) and 0.0 <= x <= 1.0


def test_answer_shapes(jev):
    a = run(jev.ask(STATE, QUESTIONS))

    assert a["refund"]["type"] == "noul" and _is_prob(a["refund"]["noul"])

    team = a["team"]
    assert team["type"] == "choice" and team["choice"] in QUESTIONS["team"]["criteria"]
    assert set(team["probabilities"]) == set(QUESTIONS["team"]["criteria"])
    assert sum(team["probabilities"].values()) == pytest.approx(1, abs=0.02)

    urg = a["urgency"]
    assert urg["type"] == "score"
    assert 0 <= urg["score"] <= len(QUESTIONS["urgency"]["criteria"]) - 1


def test_obvious_answers(jev):
    """The documented example: a double charge is billing, and it asks for a refund."""
    a = run(jev.ask(STATE, QUESTIONS))
    assert a["team"]["choice"] == "billing"
    assert a["refund"]["noul"] > 0.8


def test_grant_ranking_is_sane(config, jev):
    grants = [
        {"id": "radio", "title": "Open Radio Hardware",
         "description": "Develop open-source radio hardware for rural connectivity."},
        {"id": "bio", "title": "Molecular Biology",
         "description": "Independent research in molecular and cell biology."},
    ]
    ctx = Context(services=Services(config=config, jev=jev),
                  inputs={"profile": "Electronics engineer designing open-source LoRa and "
                                     "SDR radio hardware."}, grants=grants)
    run(jev_match_grants(ctx, include_excluded=True))
    ranked = ctx.results["matches"] + ctx.results.get("excluded", [])
    by_id = {m["grant_id"]: m for m in ranked}
    assert by_id["radio"]["probability"] > by_id["bio"]["probability"]
