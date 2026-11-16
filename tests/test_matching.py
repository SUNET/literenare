"""Question validation, value mapping and the JeV steps called directly."""
from __future__ import annotations

import pytest

from app.pipeline import Context, PipelineError
from app.pipeline.steps.matching import (answer_value, jev_alignment, jev_match_grants,
                                         validate_questions)
from app.services import Services

from .conftest import FakeJev, run

NOUL = {"type": "noul", "instructions": "?"}


# --- validate_questions ----------------------------------------------------------

@pytest.mark.parametrize("questions,rank_by,match", [
    ({}, None, "non-empty"),
    ({"q": {"type": "maybe", "instructions": "?"}}, None, "type"),
    ({"q": {"type": "noul"}}, None, "instructions"),
    ({"q": {"type": "choice", "instructions": "?", "criteria": ["a", "b"]}}, None, "mapping"),
    ({"q": {"type": "choice", "instructions": "?", "criteria": {"a": None}}}, None, "mapping"),
    ({"q": {"type": "choice", "instructions": "?", "criteria": {"a": None, "b": None},
            "positive": ["z"]}}, None, "positive"),
    ({"q": {"type": "choice", "instructions": "?", "criteria": {"a": None, "b": None},
            "min": 0.5}}, None, "positive"),
    ({"q": {"type": "score", "instructions": "?", "criteria": ["only"]}}, None, "levels"),
    ({"q": NOUL}, "missing", "not a question"),
    ({"q": {"type": "score", "instructions": "?", "criteria": ["a", "b"]}}, "q", "noul"),
])
def test_validate_rejects(questions, rank_by, match):
    with pytest.raises(PipelineError, match=match):
        validate_questions(questions, rank_by)


def test_validate_accepts_shipped_config(config):
    for section in ("matching", "alignment"):
        validate_questions(config[section]["questions"], config[section]["rank_by"], section)


# --- answer_value ----------------------------------------------------------------

def test_answer_value_noul():
    assert answer_value(NOUL, {"noul": 0.75}) == 0.75


def test_answer_value_score_normalised_by_levels():
    q = {"type": "score", "criteria": ["Routine", "Soon", "Urgent"]}
    assert answer_value(q, {"score": 0.815}) == pytest.approx(0.4075)
    assert answer_value(q, {"score": 2}) == 1.0


def test_answer_value_choice_sums_positive():
    q = {"type": "choice", "positive": ["a", "b"]}
    assert answer_value(q, {"probabilities": {"a": 0.2, "b": 0.3, "c": 0.5}}) == 0.5
    assert answer_value({"type": "choice"}, {"probabilities": {"a": 1.0}}) == 0.0


# --- steps -----------------------------------------------------------------------

GRANTS = [{"id": "weak", "title": "Biology"}, {"id": "strong", "title": "Radio"}]


def _ctx(config, inputs, grants=None):
    svc = Services(config=config, jev=FakeJev(), grants={})
    return Context(services=svc, inputs=inputs, grants=grants or [])


def test_match_step_ranks_and_gates(config):
    config["matching"]["questions"]["eligibility"]["min"] = 0.5
    ctx = _ctx(config, {"profile": "p"}, GRANTS)
    run(jev_match_grants(ctx, include_excluded=True))
    assert [m["grant_id"] for m in ctx.results["matches"]] == ["strong"]
    assert ctx.results["excluded"][0]["gated_by"] == ["eligibility"]


def test_match_step_param_overrides(config):
    questions = {"fit": NOUL}
    ctx = _ctx(config, {"profile": "p"}, GRANTS)
    run(jev_match_grants(ctx, questions=questions, rank_by="fit", top_k=1))
    assert ctx.results["rank_by"] == "fit"
    assert [m["grant_id"] for m in ctx.results["matches"]] == ["strong"]
    assert set(ctx.results["matches"][0]["answers"]) == {"fit"}


def test_match_step_falls_back_to_store(config):
    svc = Services(config=config, jev=FakeJev(), grants={g["id"]: g for g in GRANTS})
    ctx = Context(services=svc, inputs={"profile": "p"})
    run(jev_match_grants(ctx))
    assert ctx.results["considered"] == 2


def test_match_step_no_grants(config):
    ctx = _ctx(config, {"profile": "p"})
    run(jev_match_grants(ctx))
    assert ctx.results["matches"] == [] and ctx.results["considered"] == 0


def test_alignment_step(config):
    ctx = _ctx(config, {"application": "a"}, [GRANTS[1]])
    run(jev_alignment(ctx))
    assert ctx.results["alignment"]["probability"] == 0.9
    assert ctx.results["alignment"]["grant_id"] == "strong"


def test_alignment_step_needs_grant(config):
    with pytest.raises(PipelineError):
        run(jev_alignment(_ctx(config, {"application": "a"})))
