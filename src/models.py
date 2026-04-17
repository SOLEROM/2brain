from datetime import date, datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, field_validator


PageStatus = Literal["candidate", "approved", "rejected", "archived", "superseded", "partial"]
PageType = Literal[
    "source-summary", "concept", "entity", "topic", "comparison",
    "research-report", "deep-research-report", "contradiction-note", "question-answer"
]
JobStatus = Literal["queued", "running", "completed", "failed"]
JobType = Literal["digest", "deep-research", "lint", "source-discovery", "query-file"]


class RawMetadata(BaseModel):
    id: str
    title: str
    source_type: str
    origin: str
    url: Optional[str] = None
    submitted_by: Optional[str] = None
    ingested_at: str
    content_hash: str
    domain_hint: Optional[str] = None
    tags: list[str] = []
    license: Optional[str] = None
    fetch_status: str = "ok"


class SourceRef(BaseModel):
    raw_id: str
    title: Optional[str] = None
    url: Optional[str] = None


class PageFrontmatter(BaseModel):
    title: str
    domain: str
    type: PageType
    status: PageStatus
    confidence: float
    sources: list[Any] = []
    created_at: str
    updated_at: str
    tags: list[str]
    generated_by: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    candidate_id: Optional[str] = None
    candidate_operation: Optional[str] = None
    target_path: Optional[str] = None
    raw_ids: Optional[list[str]] = None
    duplicate_of: Optional[str] = None
    possible_duplicates: Optional[list[str]] = None
    origin_candidate_id: Optional[str] = None
    supersedes: Optional[str] = None
    related_pages: Optional[list[str]] = None
    open_questions: Optional[list[str]] = None
    source_paths: Optional[list[str]] = None

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {v}")
        return v

    # YAML auto-parses unquoted ISO timestamps into datetime / date objects
    # (e.g. `created_at: 2026-04-17T21:36:00+00:00`). The Claude agent doesn't
    # always quote them, so we coerce back to ISO-8601 strings before validation.
    @field_validator(
        "created_at", "updated_at", "reviewed_at",
        mode="before",
    )
    @classmethod
    def _stringify_timestamps(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, date):
            return v.isoformat()
        return v


class JobYaml(BaseModel):
    job_id: str
    job_type: JobType
    domain: str
    status: JobStatus
    created_at: str
    input: Optional[str] = None
    started_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    completed_at: Optional[str] = None
    outputs: list[str] = []
    agent: Optional[str] = None
    error: Optional[str] = None


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
