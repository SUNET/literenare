"""Minimal pipeline engine.

A *step* is an async function `fn(ctx, **params)` registered under a name.
A *pipeline* is an ordered list of step names (+ params) defined in config.yaml,
so processing order is changed by editing config, not code.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..services import Services

StepFn = Callable[..., Awaitable[None]]
STEPS: dict[str, StepFn] = {}


def step(name: str):
    """Register a pipeline step: @step("my_step") async def my_step(ctx, **params)."""
    def deco(fn: StepFn) -> StepFn:
        if name in STEPS:
            raise ValueError(f"duplicate step {name!r}")
        STEPS[name] = fn
        return fn
    return deco


@dataclass
class Context:
    services: Services
    inputs: dict[str, Any]                       # working values (steps may rewrite)
    originals: dict[str, Any] = field(default_factory=dict)
    grants: list[dict] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.originals = copy.deepcopy(self.inputs)

    @property
    def cfg(self) -> dict[str, Any]:
        return self.services.config


class PipelineError(RuntimeError):
    pass


@dataclass
class Pipeline:
    name: str
    steps: list[tuple[str, dict]]

    @classmethod
    def from_spec(cls, name: str, spec: list) -> "Pipeline":
        steps = []
        for item in spec:
            if isinstance(item, str):
                sname, params = item, {}
            elif isinstance(item, dict) and len(item) == 1:
                sname, params = next(iter(item.items()))
                params = params or {}
            else:
                raise PipelineError(f"{name}: bad step spec {item!r}")
            if sname not in STEPS:
                raise PipelineError(f"{name}: unknown step {sname!r}. Known: {sorted(STEPS)}")
            steps.append((sname, params))
        return cls(name, steps)

    async def run(self, ctx: Context) -> Context:
        for sname, params in self.steps:
            t0 = time.perf_counter()
            await STEPS[sname](ctx, **params)
            ctx.trace.append({"step": sname, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        return ctx


def build_pipelines(cfg: dict[str, Any]) -> dict[str, Pipeline]:
    from . import steps  # noqa: F401  (registers built-in steps)

    return {n: Pipeline.from_spec(n, spec) for n, spec in cfg.get("pipelines", {}).items()}
