"""Shared fixtures. Unit tests use fakes / mocked HTTP; tests/live/ hits a real server."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.main import create_app
from app.services import Services, load_grants

ROOT = Path(__file__).resolve().parents[1]
API_KEY = "test-key"


class FakeJev:
    """Deterministic stand-in for a /v1/systemone backend.

    Anything whose grant (or, without a grant, the whole state) mentions "radio" is a
    strong match (noul 0.9, top score level); everything else is weak (noul 0.4, level 0).
    Records every call in `.calls` so tests can assert on batching.
    """
    model = "fake"

    def __init__(self):
        self.calls: list[tuple] = []

    async def ask(self, state, questions):
        self.calls.append((state, questions))
        target = state.get("grant", state) if isinstance(state, dict) else state
        hit = "radio" in str(target).lower()
        out = {}
        for name, q in questions.items():
            if q["type"] == "noul":
                out[name] = {"type": "noul", "noul": 0.9 if hit else 0.4}
            elif q["type"] == "score":
                top = len(q["criteria"]) - 1
                out[name] = {"type": "score", "score": float(top if hit else 0),
                             "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                             "probabilities": {}}
            else:
                keys = list(q["criteria"])
                out[name] = {"type": "choice", "choice": keys[0],
                             "probabilities": {k: 1 / len(keys) for k in keys}}
        return out


@pytest.fixture
def config():
    cfg = load_config(ROOT / "config.yaml")
    cfg["server"]["api_keys"] = API_KEY
    return cfg


@pytest.fixture
def fake_jev():
    return FakeJev()


@pytest.fixture
def client(config, fake_jev):
    svc = Services(config=config, jev=fake_jev,
                   grants=load_grants(str(ROOT / "data/grants.json")))
    with TestClient(create_app(config, svc)) as c:
        c.headers["X-API-Key"] = API_KEY
        yield c


def mock_http(backend, handler):
    """Route a backend client's HTTP through `handler(httpx.Request) -> httpx.Response`."""
    backend._http = httpx.AsyncClient(base_url=backend._base,
                                      transport=httpx.MockTransport(handler))
    return backend


def run(coro):
    return asyncio.run(coro)
