"""JeV System 1 clients.

Internally everything speaks the `/v1/systemone` shape:

    questions: {name: {type: noul|choice|score, instructions: str, criteria: ...}}
    answers:   {name: {type: noul,   noul: p}
                       {type: choice, choice, probabilities: {key: p}, confidence?}
                       {type: score,  score, legend, probabilities: {"0": p, ...}, confidence?}}

`SystemOneClient` sends that natively (all questions about one state in one request).
`DecideClient` adapts autotrust's serve_decide.py `/v1/decide` (one question per request).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

# Our own per-question keys; never sent to the model server.
LOCAL_KEYS = {"min", "positive"}


class BackendError(RuntimeError):
    pass


class _Http:
    path = ""

    def __init__(self, base_url: str, model: str = "", api_key: str = "",
                 concurrency: int = 16, timeout: float = 60, **_: Any):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._base, headers=headers, timeout=timeout)
        self._sem = asyncio.Semaphore(int(concurrency))

    async def _post(self, path: str, body: dict) -> dict:
        async with self._sem:
            try:
                r = await self._http.post(path, json=body)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise BackendError(f"{self._base}{path}: {e}") from e
            return r.json()

    async def aclose(self) -> None:
        await self._http.aclose()


class SystemOneClient(_Http):
    async def ask(self, state: str | dict, questions: dict[str, dict]) -> dict[str, dict]:
        wire = {n: {k: v for k, v in q.items() if k not in LOCAL_KEYS}
                for n, q in questions.items()}
        body: dict[str, Any] = {"state": state, "questions": wire}
        if self.model:
            body["model"] = self.model
        answers = (await self._post("/systemone", body)).get("answers") or {}
        missing = set(questions) - set(answers)
        if missing:
            raise BackendError(f"/systemone returned no answer for {sorted(missing)}")
        return {n: answers[n] for n in questions}


class DecideClient(_Http):
    async def _decide(self, kind: str, state: Any, question: str,
                      options: list[str] | None = None) -> dict[str, float]:
        body: dict[str, Any] = {"kind": kind, "state": state, "question": question}
        if options:
            body["options"] = options
        data = await self._post("/decide", body)
        return dict(zip(data["options"], data["probabilities"]))

    async def _one(self, state: Any, q: dict) -> dict:
        t, text, crit = q["type"], q["instructions"], q.get("criteria")
        if t == "noul":
            return {"type": "noul", "noul": (await self._decide("noul", state, text)).get("true", 0.0)}
        if t == "choice":
            keys = list(crit)
            opts = [f"{k}: {v}" if v else k for k, v in crit.items()]
            p = await self._decide("choice", state, text, opts)
            probs = {k: p[o] for k, o in zip(keys, opts)}
            return {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}
        # score: ask as a choice over the ordered levels, report the expected level index.
        p = await self._decide("choice", state, text, list(crit))
        probs = {str(i): p[level] for i, level in enumerate(crit)}
        return {"type": "score", "score": sum(i * p[level] for i, level in enumerate(crit)),
                "legend": {str(i): level for i, level in enumerate(crit)}, "probabilities": probs}

    async def ask(self, state: str | dict, questions: dict[str, dict]) -> dict[str, dict]:
        names = list(questions)
        answers = await asyncio.gather(*(self._one(state, questions[n]) for n in names))
        return dict(zip(names, answers))


PROTOCOLS = {"systemone": SystemOneClient, "decide": DecideClient}


def make_jev_client(protocol: str = "systemone", **kwargs: Any) -> _Http:
    if protocol not in PROTOCOLS:
        raise ValueError(f"backends.jev.protocol must be one of {sorted(PROTOCOLS)}")
    return PROTOCOLS[protocol](**kwargs)
