# literenare

## Goal

The goal with this project is to develop an AI-focused API backend for the it42 project. 

This backend filters and serves suggestions, streamlining the user experience for grantees, granters and other people on the platform.

## Technical Decisions:

 - Use JeV-style models in order to get quick ordering and a point based matching.
 - Use open-weighted models only.
 - Using traditional Large Language Models (LLMs) only in order to perform more complex tasks.

## Platform

 - Lang: Python
 - Compatible with OpenAI-style endpoints
 - Configurable API base prompts, concurrency, endpoints and keys.

## Future Choices

 - Using in-house models to increase accuracy
 - Context-aware translation in order to ensure accuracy along the whole chain
	- Open-weighted JeV models are primarily trained in English.
	- Make the whole chain English, using e.g. Translategemma in the beginning and end.
	- (IN) Swedish -> (AI Processing) English -> (OUT) Swedish

# Hurdles

 - Conflict of Interest
 - Matching fields 



## API (JeV)

FastAPI service that matches grants and checks applications with a JeV System 1 model,
served with Granian. Each endpoint runs an ordered list of steps from `config.yaml`, so
processing can be reordered or extended without touching the endpoints.

### Run

```bash
cp .env.example .env              # JEV_BASE_URL / JEV_MODEL / keys
docker compose up --build         # API on :8080, docs at /docs
```

Local dev:

```bash
pip install -r requirements-dev.txt && pytest          # unit tests, fake / mocked backends
JEV_BASE_URL=http://localhost:11434/v1 granian --interface asgi --factory app.main:create_app --port 8080
```

### Tests

```
tests/
  conftest.py          shared fixtures: FakeJev backend, TestClient, mocked HTTP helper
  test_api.py          HTTP endpoints (auth, match, align, /v1/systemone, introspection)
  test_clients.py      systemone + decide clients against mocked HTTP, wire format
  test_matching.py     question validation, value mapping, matching/alignment steps
  test_pipeline.py     step registry, ordering, trace, config loading
  live/                real-server tests, skipped unless JEV_LIVE_URL is set
  curl/
    run.sh             curl smoke test of every endpoint against a running API
    requests/*.json    request bodies, reusable with curl -d @file
```

```bash
pytest                                                             # everything offline
JEV_LIVE_URL=http://localhost:11434/v1 JEV_LIVE_MODEL=nimble pytest tests/live -v
JEV_LIVE_URL=http://localhost:8000/v1 JEV_LIVE_PROTOCOL=decide pytest tests/live -v
```

Against a running API (`docker compose up`); needs bash + curl, jq optional:

```bash
tests/curl/run.sh                          # every endpoint, pass/fail + one-line summaries
tests/curl/run.sh match                    # only checks whose name contains "match"
tests/curl/run.sh -v systemone             # also show the curl command and full response
BASE_URL=http://server:8080 API_KEY=secret tests/curl/run.sh

curl -s localhost:8080/v1/grants/match -H 'content-type: application/json' \
  -d @tests/curl/requests/match_profile.json | jq
```

The exit code is the number of failed checks, so it can gate a deploy. A 502 means the
API is up but can't reach the JeV backend.

### Backends

| `JEV_PROTOCOL` | Server | Requests |
|---|---|---|
| `systemone` (default) | anything exposing `POST /v1/systemone` | one request per state, all questions batched |
| `decide` | autotrust `serve_decide.py` (`POST /v1/decide`) | one request per question, converted to systemone answers |

Internally, questions and answers always use the `/v1/systemone` format, so the
steps don't depend on which backend is configured.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/grants/match` | Grants for a profile, ordered by P(match) |
| POST | `/v1/applications/align` | P(application fits grant) + detail answers |
| POST | `/v1/systemone` | Ask typed questions directly (`/v1/systemone` format, any backend) |
| GET  | `/v1/grants` | Grants in the store (`data/grants.json`) |
| GET  | `/v1/pipelines`, `/v1/steps` | Configured pipelines / available steps |
| POST | `/v1/pipelines/{name}/run` | Run any pipeline with arbitrary `inputs` |

```bash
curl -s localhost:8080/v1/grants/match -H 'content-type: application/json' \
  -d '{"profile": "I research open radio hardware for rural connectivity.", "top_k": 5}'
```

```json
{
  "pipeline": "grant_match",
  "matches": [
    {"grant_id": "example-rf-hardware", "title": "...", "probability": 0.93,
     "answers": {"match": {"type": "noul", "noul": 0.93},
                 "eligibility": {"type": "noul", "noul": 0.88},
                 "no_conflict_of_interest": {"type": "noul", "noul": 0.97}},
     "gated_by": []}
  ],
  "considered": 3, "rank_by": "match",
  "trace": [{"step": "jev_match_grants", "ms": 412.0}]
}
```

### Ranking

Grants are ordered by the P(true) of the `rank_by` question (a `noul`, "is this grant a
good match for the applicant?"). Other questions are returned in `answers` and can act as
gates with `min`. A grant is dropped if the answer's value is below `min`: P(true) for
`noul`, `score / (levels - 1)` for `score`, or the summed probability of the `positive`
keys for `choice`. Questions, `rank_by` and gates all live in `config.yaml` and are
validated at startup.

### Adding a step

```python
# app/pipeline/steps/my_step.py  (and import it in steps/__init__.py)
from ..core import Context, step

@step("prefilter")
async def prefilter(ctx: Context, keep: int = 200):
    ctx.grants = ctx.grants[:keep]
```

Then add `- prefilter: {keep: 100}` before `jev_match_grants` in `config.yaml`.

### Notes

- Input goes to JeV as-is. Non-English profiles depend on how well the model handles that language.
- Matching costs one request per grant (systemone). The profile is placed first in the
  state, so servers with prefix caching reuse it across grants.
- `backends.jev.concurrency` is per Granian worker. Total in-flight = concurrency × `GRANIAN_WORKERS`.
- In Docker, `localhost` means the container. The default `host.docker.internal` reaches
  a model server on the host. Compose maps it on Linux too.
