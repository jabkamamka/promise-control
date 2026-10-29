"""Pydantic-схемы запросов и ответов."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["created", "in_progress", "done"]


class Replica(BaseModel):
    model_config = ConfigDict(extra="allow")
    speaker: str
    text: str


class CallIn(BaseModel):
    """Звонок от программы-отправителя."""

    model_config = ConfigDict(extra="allow")

    id: str
    operator_id: int | str | None = None
    client_phone: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    transcript: list[Replica] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("id звонка не может быть пустым")
        return str(v).strip()


class IngestCallResult(BaseModel):
    call_id: str
    status: Literal["processed", "duplicate", "error"]
    tasks_created: int = 0
    promises_found: int = 0
    tasks_verified: int = 0
    error: str | None = None


class IngestResponse(BaseModel):
    received: int
    processed: int
    duplicates: int
    failed: int
    tasks_created: int
    tasks_verified: int = 0
    calls: list[IngestCallResult]


class TaskOut(BaseModel):
    id: str
    call_id: str
    operator_id: int | None = None
    client_phone: str | None = None
    promise_type: str
    promise_type_title: str | None = None
    title: str
    object: str = ""
    quote: str
    transcript_index: int
    actions: list[str] = Field(default_factory=list)
    secondary_types: list[str] = Field(default_factory=list)
    due_at: str
    due_hint: str = ""
    deadline_source: str
    status: str
    effective_status: str
    is_overdue: bool
    confidence: float
    matched_by: str
    created_at: str
    updated_at: str
    closed_at: str | None = None
    verification_status: str | None = None
    verified_at: str | None = None
    verified_call_id: str | None = None
    verification_quote: str | None = None
    call_started_at: str | None = None
    call_ended_at: str | None = None


class TaskList(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int


class TaskStatusUpdate(BaseModel):
    status: Status
    comment: str | None = Field(default=None, max_length=1000)


class TaskEvent(BaseModel):
    id: int
    task_id: str
    event: str
    from_status: str | None = None
    to_status: str | None = None
    comment: str | None = None
    at: str


class PromiseTypeIn(BaseModel):
    code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_\-]*$")
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    examples: list[str] = Field(default_factory=list, max_length=50)
    priority: int | None = Field(default=None, ge=1, le=100)


class PromiseTypeOut(BaseModel):
    code: str
    title: str
    description: str
    keywords: list[str]
    examples: list[str]
    is_builtin: bool
    priority: int
    created_at: str
    updated_at: str
    tasks_count: int = 0


class TemplateOut(BaseModel):
    config: dict[str, Any]


class StatsOut(BaseModel):
    calls_total: int
    tasks_total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    by_verification: dict[str, int]
    overdue: int
    not_fulfilled: int
    due_today: int
    avg_promises_per_call: float


class CallOut(BaseModel):
    id: str
    operator_id: int | None = None
    client_phone: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    received_at: str
    processed_at: str | None = None
    promise_count: int
    status: str
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[TaskOut] = Field(default_factory=list)


class CallList(BaseModel):
    items: list[CallOut]
    total: int
    limit: int
    offset: int


class HealthOut(BaseModel):
    status: str
    version: str
    time: str
    database: str
    timezone: str
    types: int
    tasks: int
