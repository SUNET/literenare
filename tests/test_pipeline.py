"""Pipeline engine and config loading."""
from __future__ import annotations

import pytest

from app.config import load_config
from app.pipeline import STEPS, Context, Pipeline, PipelineError, build_pipelines, step
from app.services import Services

from .conftest import FakeJev, run


@pytest.fixture
def scratch_steps():
    """Register throwaway steps for one test and remove them afterwards."""
    before = set(STEPS)
    yield
    for name in set(STEPS) - before:
        del STEPS[name]


def test_spec_forms(scratch_steps):
    @step("t_a")
    async def a(ctx, x=1):
        ctx.results.setdefault("seen", []).append(("a", x))

    p = Pipeline.from_spec("p", ["t_a", {"t_a": {"x": 2}}, {"t_a": None}])
    assert p.steps == [("t_a", {}), ("t_a", {"x": 2}), ("t_a", {})]


def test_unknown_and_malformed_steps():
    with pytest.raises(PipelineError, match="unknown step"):
        Pipeline.from_spec("p", ["nope"])
    with pytest.raises(PipelineError, match="bad step spec"):
        Pipeline.from_spec("p", [{"a": {}, "b": {}}])


def test_duplicate_registration_rejected(scratch_steps):
    @step("t_dup")
    async def one(ctx):
        pass

    with pytest.raises(ValueError):
        @step("t_dup")
        async def two(ctx):
            pass


def test_steps_run_in_config_order_with_trace(config, scratch_steps):
    @step("t_upper")
    async def upper(ctx, field="text"):
        ctx.inputs[field] = ctx.inputs[field].upper()

    @step("t_suffix")
    async def suffix(ctx, field="text", s="!"):
        ctx.inputs[field] += s

    ctx_a = Context(services=Services(config=config, jev=FakeJev()), inputs={"text": "hi"})
    ctx_b = Context(services=Services(config=config, jev=FakeJev()), inputs={"text": "hi"})
    run(Pipeline.from_spec("a", ["t_upper", {"t_suffix": {"s": "?"}}]).run(ctx_a))
    run(Pipeline.from_spec("b", [{"t_suffix": {"s": "?"}}, "t_upper"]).run(ctx_b))

    assert ctx_a.inputs["text"] == "HI?" and ctx_b.inputs["text"] == "HI?"
    assert ctx_a.originals["text"] == "hi"                 # originals untouched
    assert [t["step"] for t in ctx_a.trace] == ["t_upper", "t_suffix"]
    assert all(t["ms"] >= 0 for t in ctx_a.trace)


def test_build_pipelines_from_shipped_config(config):
    pipelines = build_pipelines(config)
    assert [s for s, _ in pipelines["grant_match"].steps] == ["jev_match_grants"]
    assert [s for s, _ in pipelines["application_alignment"].steps] == ["jev_alignment"]


def test_config_env_expansion(tmp_path, monkeypatch):
    f = tmp_path / "c.yaml"
    f.write_text("a: ${T_SET:-x}\nb: ${T_UNSET:-fallback}\nc: ${T_EMPTY}\nd: [\"${T_SET}\"]\n")
    monkeypatch.setenv("T_SET", "value")
    monkeypatch.delenv("T_UNSET", raising=False)
    monkeypatch.delenv("T_EMPTY", raising=False)
    assert load_config(f) == {"a": "value", "b": "fallback", "c": "", "d": ["value"]}


def test_startup_rejects_bad_config(config, fake_jev):
    from fastapi.testclient import TestClient

    from app.main import create_app

    config["matching"]["rank_by"] = "eligibility_typo"
    with pytest.raises(PipelineError, match="rank_by"):
        with TestClient(create_app(config, Services(config=config, jev=fake_jev))):
            pass
