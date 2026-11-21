"""Typed request/response models shared by the dry-run route and the language patchers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

PatchOpKind = Literal[
    "add_field",
    "update_field",
    "remove_field",
    "add_annotation",
    "remove_annotation",
    "add_dependency",
    "remove_dependency",
]


class PatchModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class PatchField(PatchModel):
    name: str = Field(..., min_length=1)
    type: str = ""
    visibility: str | None = None
    annotations: list[str] = Field(default_factory=list)


class PatchOperation(PatchModel):
    op: PatchOpKind
    file_path: str = Field(..., min_length=1)
    type_name: str | None = None
    field_name: str | None = None
    original_name: str | None = None
    field: PatchField | None = None
    annotation: str | None = None


class DryRunRequest(PatchModel):
    root_path: str = Field(..., min_length=1)
    operations: list[PatchOperation] = Field(..., min_length=1, max_length=500)


class PatchResult(PatchModel):
    file_path: str
    language: str
    original_content: str
    proposed_content: str
    summary: str
    warnings: list[str] = Field(default_factory=list)


class DryRunResponse(PatchModel):
    patches: list[PatchResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@dataclass
class PatchOutcome:
    """Result of applying operations to one in-memory file."""

    content: str
    applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def summarize(outcome: PatchOutcome) -> str:
    if not outcome.applied:
        suffix = f" ({len(outcome.warnings)} warning(s))" if outcome.warnings else ""
        return f"No changes proposed{suffix}"

    counts = Counter(item.split(" ", 1)[0] for item in outcome.applied)
    details = ", ".join(f"{name} ×{counts[name]}" for name in sorted(counts))
    suffix = f"; {len(outcome.warnings)} warning(s)" if outcome.warnings else ""
    return f"{len(outcome.applied)} operation(s) applied: {details}{suffix}"
