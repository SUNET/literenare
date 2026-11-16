from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Grant(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str = ""
    funder: str = ""
    description: str = ""
    eligibility: str = ""
    focus_areas: list[str] = Field(default_factory=list)


class GrantSelection(BaseModel):
    grant_ids: list[str] | None = Field(None, description="Pick grants from the store")
    grants: list[Grant] | None = Field(None, description="Or send grants inline")


class MatchRequest(GrantSelection):
    profile: str | dict[str, Any] = Field(..., description="Free text or structured profile")
    top_k: int | None = None
    pipeline: str = "grant_match"


class AlignRequest(GrantSelection):
    application: str
    grant_id: str | None = None
    pipeline: str = "application_alignment"


class Question(BaseModel):
    type: Literal["noul", "choice", "score"]
    instructions: str
    criteria: dict[str, str | None] | list[str] | None = None


class SystemOneRequest(BaseModel):
    """Same shape as /v1/systemone; `model` is ignored (the configured model is used)."""
    model: str | None = None
    state: str | dict[str, Any]
    questions: dict[str, Question]


class RunRequest(GrantSelection):
    inputs: dict[str, Any]
