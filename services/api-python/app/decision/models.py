"""Wire contracts for the System 1 decision API (camelCase JSON, strict validation)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.decision.config import SystemOneOverride
from app.models.ir import WorkspaceIR


class DecisionModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class DiffPatchInput(DecisionModel):
    file_path: str = Field(..., min_length=1, max_length=1024)
    original_content: str = Field(default="", max_length=400_000)
    proposed_content: str = Field(default="", max_length=400_000)
    is_new_file: bool = False


class TestConnectionRequest(DecisionModel):
    system_one_config: SystemOneOverride | None = None


class TriageAuditRequest(DecisionModel):
    root_path: str = Field(..., min_length=1)
    workspace_ir: WorkspaceIR
    finding_ids: list[str] | None = Field(default=None, max_length=200)
    system_one_config: SystemOneOverride | None = None


class RouteTaskRequest(DecisionModel):
    root_path: str = Field(..., min_length=1)
    intent: str = Field(..., min_length=3, max_length=4_000)
    workspace_ir: WorkspaceIR
    target_node_id: str | None = Field(default=None, max_length=300)
    system_one_config: SystemOneOverride | None = None


class ScreenDiffRequest(DecisionModel):
    root_path: str = Field(..., min_length=1)
    patches: list[DiffPatchInput] = Field(..., min_length=1, max_length=50)
    workspace_ir: WorkspaceIR | None = None
    system_one_config: SystemOneOverride | None = None


class SystemOneTestResponse(DecisionModel):
    reachable: bool
    latency_ms: int
    model: str
    provider_hint: str
    warning: str | None = None
    error_code: str | None = None


class TriageItemResponse(DecisionModel):
    adr_id: str
    finding_id: str
    risk_level: str
    recommended_route: str
    confidence: float
    escalated_to_system2: bool
    priority: float
    answers: dict[str, Any] = Field(default_factory=dict)


class TriageAuditResponse(DecisionModel):
    available: bool
    model: str
    latency_ms: int
    items: list[TriageItemResponse] = Field(default_factory=list)
    warning: str | None = None


class RouteTaskResponse(DecisionModel):
    available: bool
    adr_id: str | None = None
    recommended_route: str
    blast_radius: str
    confidence: float
    escalate_to_system2: bool
    rationale: str
    answers: dict[str, Any] = Field(default_factory=dict)
    warning: str | None = None


class ScreenDiffResponse(DecisionModel):
    available: bool
    adr_id: str | None = None
    status: str
    confidence: float
    flags: list[str] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)
    advisory_note: str
    warning: str | None = None


class DecisionSummary(DecisionModel):
    id: str
    workspace_path: str
    decision_type: str
    subject: str
    model: str
    recommended_route: str
    confidence: float
    latency_ms: int
    feedback_status: str
    override_route: str | None = None
    feedback_note: str | None = None
    created_at: str
    feedback_at: str | None = None
    answers: dict[str, Any] = Field(default_factory=dict)


class DecisionListResponse(DecisionModel):
    decisions: list[DecisionSummary] = Field(default_factory=list)


class DecisionFeedbackRequest(DecisionModel):
    status: Literal["accepted", "overridden"]
    override_route: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=2000)


__all__ = [
    "DecisionFeedbackRequest",
    "DecisionListResponse",
    "DecisionSummary",
    "DiffPatchInput",
    "RouteTaskRequest",
    "RouteTaskResponse",
    "ScreenDiffRequest",
    "ScreenDiffResponse",
    "SystemOneTestResponse",
    "TestConnectionRequest",
    "TriageAuditRequest",
    "TriageAuditResponse",
    "TriageItemResponse",
]
