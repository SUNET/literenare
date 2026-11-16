from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..backends import BackendError
from ..pipeline import STEPS, Context, PipelineError
from ..pipeline.steps.matching import validate_questions
from .schemas import AlignRequest, GrantSelection, MatchRequest, RunRequest, SystemOneRequest


def require_key(request: Request) -> None:
    keys = request.app.state.api_keys
    if not keys:
        return
    auth = request.headers.get("authorization", "")
    given = request.headers.get("x-api-key") or auth.removeprefix("Bearer ").strip()
    if given not in keys:
        raise HTTPException(401, "invalid or missing API key")


router = APIRouter(prefix="/v1", dependencies=[Depends(require_key)])


def _select_grants(request: Request, sel: GrantSelection,
                   extra_ids: list[str] | None = None) -> list[dict]:
    store = request.app.state.services.grants
    grants = [g.model_dump() for g in sel.grants or []]
    for gid in (sel.grant_ids or []) + (extra_ids or []):
        if gid not in store:
            raise HTTPException(404, f"unknown grant {gid!r}")
        grants.append(store[gid])
    return grants


async def run_pipeline(request: Request, name: str, inputs: dict[str, Any],
                       grants: list[dict]) -> dict:
    pipelines = request.app.state.pipelines
    if name not in pipelines:
        raise HTTPException(404, f"unknown pipeline {name!r}")
    ctx = Context(services=request.app.state.services, inputs=inputs, grants=grants)
    try:
        await pipelines[name].run(ctx)
    except PipelineError as e:
        raise HTTPException(400, str(e)) from e
    except BackendError as e:
        raise HTTPException(502, str(e)) from e
    return {"pipeline": name, **ctx.results, "trace": ctx.trace}


# --- Task endpoints ----------------------------------------------------------

@router.post("/grants/match", summary="Rank grants for a profile by P(match)")
async def match_grants(req: MatchRequest, request: Request):
    inputs: dict[str, Any] = {"profile": req.profile}
    if req.top_k:
        inputs["top_k"] = req.top_k
    return await run_pipeline(request, req.pipeline, inputs, _select_grants(request, req))


@router.post("/applications/align", summary="P(application fits grant) plus detail answers")
async def align_application(req: AlignRequest, request: Request):
    grants = _select_grants(request, req, [req.grant_id] if req.grant_id else None)
    if not grants:
        raise HTTPException(422, "provide grant_id, grant_ids or grants")
    return await run_pipeline(request, req.pipeline, {"application": req.application}, grants)


@router.post("/systemone", summary="Ask JeV typed questions (/v1/systemone format)")
async def systemone(req: SystemOneRequest, request: Request):
    """Works with either backend protocol; answers always come back in systemone shape."""
    questions = {n: q.model_dump(exclude_none=True) for n, q in req.questions.items()}
    try:
        validate_questions(questions)
        answers = await request.app.state.services.jev.ask(req.state, questions)
    except PipelineError as e:
        raise HTTPException(422, str(e)) from e
    except BackendError as e:
        raise HTTPException(502, str(e)) from e
    return {"model": request.app.state.services.jev.model, "answers": answers}


# --- Grants store --------------------------------------------------------------

@router.get("/grants", summary="List grants in the store")
async def list_grants(request: Request):
    return list(request.app.state.services.grants.values())


# --- Generic pipeline access (for experimenting with new orderings) ----------

@router.get("/pipelines", summary="Configured pipelines and their step order")
async def list_pipelines(request: Request):
    return {n: [{"step": s, "params": p} for s, p in pl.steps]
            for n, pl in request.app.state.pipelines.items()}


@router.get("/steps", summary="Registered steps and their parameters")
async def list_steps():
    out = {}
    for name, fn in STEPS.items():
        params = {k: (None if v.default is inspect.Parameter.empty else v.default)
                  for k, v in list(inspect.signature(fn).parameters.items())[1:]}
        out[name] = {"doc": inspect.getdoc(fn), "params": params}
    return out


@router.post("/pipelines/{name}/run", summary="Run any configured pipeline")
async def run_named(name: str, req: RunRequest, request: Request):
    return await run_pipeline(request, name, req.inputs, _select_grants(request, req))
