"""JeV (System 1) grant matching and application alignment.

Ranking key: P(true) of the `rank_by` noul question ("is this a match?").
Other questions are reported alongside and can gate a grant out with `min`.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..core import Context, PipelineError, step

TYPES = {"noul", "choice", "score"}


def validate_questions(questions: dict[str, dict], rank_by: str | None = None,
                       where: str = "questions") -> None:
    if not isinstance(questions, dict) or not questions:
        raise PipelineError(f"{where}: must be a non-empty mapping of name -> question")
    for name, q in questions.items():
        t = q.get("type")
        if t not in TYPES:
            raise PipelineError(f"{where}.{name}: type must be one of {sorted(TYPES)}")
        if not q.get("instructions"):
            raise PipelineError(f"{where}.{name}: instructions required")
        crit = q.get("criteria")
        if t == "choice":
            if not isinstance(crit, dict) or len(crit) < 2:
                raise PipelineError(f"{where}.{name}: choice needs a criteria mapping (>= 2)")
            if not set(q.get("positive") or []) <= set(crit):
                raise PipelineError(f"{where}.{name}: positive must be criteria keys")
            if "min" in q and not q.get("positive"):
                raise PipelineError(f"{where}.{name}: a gated choice needs `positive` keys")
        if t == "score" and (not isinstance(crit, list) or len(crit) < 2):
            raise PipelineError(f"{where}.{name}: score needs a criteria list (>= 2 levels)")
    if rank_by is not None:
        if rank_by not in questions:
            raise PipelineError(f"{where}: rank_by {rank_by!r} is not a question")
        if questions[rank_by]["type"] != "noul":
            raise PipelineError(f"{where}: rank_by must be a noul question (a probability)")


def answer_value(q: dict, a: dict) -> float:
    """Collapse an answer to 0..1 (used for gating with `min`)."""
    if q["type"] == "noul":
        return float(a["noul"])
    if q["type"] == "choice":
        return sum(a["probabilities"].get(k, 0.0) for k in q.get("positive", []))
    return float(a["score"]) / (len(q["criteria"]) - 1)


async def evaluate(jev, state: Any, questions: dict[str, dict]) -> dict:
    answers = await jev.ask(state, questions)
    gated_by = []
    for name, q in questions.items():
        a = answers[name]
        if "min" in q and answer_value(q, a) < float(q["min"]):
            gated_by.append(name)
    return {"answers": answers, "gated_by": gated_by}


def _grant_state(grant: dict, fields: list[str]) -> dict:
    return {k: grant[k] for k in fields if grant.get(k) not in (None, "", [])}


@step("jev_match_grants")
async def jev_match_grants(ctx: Context, field: str = "profile",
                           questions: dict | None = None, rank_by: str | None = None,
                           top_k: int | None = None, include_excluded: bool = False) -> None:
    """Rank grants by P(match) for one profile; drop grants that fail a `min` gate."""
    mcfg = ctx.cfg["matching"]
    questions = questions or mcfg["questions"]
    rank_by = rank_by or mcfg["rank_by"]
    top_k = int(top_k or ctx.inputs.get("top_k") or mcfg.get("top_k", 20))
    grants = ctx.grants or list(ctx.services.grants.values())
    profile = ctx.inputs[field]

    async def one(grant: dict) -> dict:
        # Profile first so many grants share a prompt prefix (server-side prefix caching).
        state = {"applicant_profile": profile,
                 "grant": _grant_state(grant, mcfg["grant_fields"])}
        ev = await evaluate(ctx.services.jev, state, questions)
        return {"grant_id": grant.get("id"), "title": grant.get("title"),
                "probability": round(float(ev["answers"][rank_by]["noul"]), 4), **ev}

    scored = await asyncio.gather(*(one(g) for g in grants))
    kept = sorted((s for s in scored if not s["gated_by"]), key=lambda s: -s["probability"])
    ctx.results["matches"] = kept[:top_k]
    ctx.results["considered"] = len(scored)
    ctx.results["rank_by"] = rank_by
    if include_excluded:
        ctx.results["excluded"] = [s for s in scored if s["gated_by"]]


@step("jev_alignment")
async def jev_alignment(ctx: Context, field: str = "application",
                        questions: dict | None = None, rank_by: str | None = None) -> None:
    """Ask the alignment questions about one application against one grant."""
    if not ctx.grants:
        raise PipelineError("jev_alignment needs a grant")
    acfg = ctx.cfg["alignment"]
    questions = questions or acfg["questions"]
    rank_by = rank_by or acfg["rank_by"]
    state = {"grant": _grant_state(ctx.grants[0], ctx.cfg["matching"]["grant_fields"]),
             "application": ctx.inputs[field]}
    ev = await evaluate(ctx.services.jev, state, questions)
    ctx.results["alignment"] = {"grant_id": ctx.grants[0].get("id"),
                                "probability": round(float(ev["answers"][rank_by]["noul"]), 4),
                                **ev}
