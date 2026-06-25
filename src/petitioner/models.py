"""Domain models — the normalized schema (spec §6).

These are the in-memory representations produced by normalize.py and persisted by
store.py. Storage uses snapshot-latest semantics for comments (decision D1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    PARTIAL = "partial"


class Tag(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag_id: str
    name: str | None
    slug: str | None


class Comment(BaseModel):
    comment_id: str
    petition_id: str
    text: str | None
    role: str | None
    likes: int | None
    city: str | None
    created_at: datetime | None
    observed_in_run: str


class Petition(BaseModel):
    petition_id: str
    slug: str
    url: str
    title: str | None
    description: str | None
    signatures_total: int | None
    signatures_displayed: int | None
    signatures_displayed_localized: str | None
    goal: int | None
    created_at: datetime | None
    creator_name: str | None
    creator_location: str | None
    organization: str | None
    is_verified_victory: bool | None
    status: str | None
    comment_total: int
    language: str | None
    tags: list[Tag] = []


class Observation(BaseModel):
    observation_id: str
    petition_id: str
    run_id: str
    captured_at: datetime
    raw_payload_ref: str
    comment_completeness: float


class Run(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    query_or_targets: str
    adapter_version: str
    status: RunStatus
