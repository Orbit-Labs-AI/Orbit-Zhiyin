"""Versioned desktop response shapes; raw session payloads stay outside lifecycle state."""

from typing import Any, Literal

from pydantic import BaseModel, Field

JobStatus = Literal[
    "queued", "running", "completed", "partial", "cancelled", "failed", "interrupted"
]


class JobProgress(BaseModel):
    stage: str | None = None
    agent: str | None = None
    completed: int | None = None
    total: int | None = None


class JobResponse(BaseModel):
    id: str
    kind: str
    status: JobStatus
    created_at: int
    source_ids: list[str]
    selection: Literal["full", "sample"]
    limit: int | None = None
    files_by_source: dict[str, list[str]] = Field(default_factory=dict)
    started_at: int | None = None
    finished_at: int | None = None
    cancel_requested: bool = False
    progress: JobProgress = Field(default_factory=JobProgress)
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class SourceResponse(BaseModel):
    id: str
    agent: str
    root: str
    enabled: bool
    last_import_at: int | None = None
    last_result: dict[str, Any] | None = None


class StorageResponse(BaseModel):
    readiness: Literal["ready", "rebuild_required"]
    projection_run_id: int | None
    schema_version: int
    tables: dict[str, int]
    sources: list[dict[str, Any]]
    archive_bytes: int
    database_bytes: int
    home: str
