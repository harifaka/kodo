"""Typed request/response models for sandboxed build verification (Phase 9).

The builder never accepts a host path beyond the workspace root, never receives a command and never
receives anything but an allow-listed image name. ``patches`` are in-memory proposals overlaid on a
staged tar snapshot, so a proposed fix can be compiled without touching the user's disk.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

BuildStackId = Literal["java", "csharp", "nodejs", "python"]
BuildStatusId = Literal["passed", "failed", "timeout", "unavailable"]
BuildSeverity = Literal["error", "warning"]


class BuildModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class BuildPatchInput(BuildModel):
    """One in-memory file proposal, validated against the workspace root before staging."""

    file_path: str = Field(..., min_length=1, max_length=1_024)
    proposed_content: str = Field(..., max_length=2_000_000)
    is_new_file: bool = False


class BuildDiagnostic(BuildModel):
    file_path: str
    line: int = Field(default=0, ge=0)
    column: int = Field(default=0, ge=0)
    severity: BuildSeverity = "error"
    code: str = ""
    message: str = ""


class BuilderStatus(BuildModel):
    enabled: bool
    docker_available: bool
    daemon_running: bool
    images: dict[str, bool] = Field(default_factory=dict)
    warning: str | None = None


class BuildVerifyRequest(BuildModel):
    root_path: str = Field(..., min_length=1)
    stack: BuildStackId | None = None
    patches: list[BuildPatchInput] = Field(default_factory=list, max_length=200)
    run_tests: bool = False


class BuildResult(BuildModel):
    build_id: str
    stack: str
    status: BuildStatusId
    exit_code: int | None = None
    duration_ms: int = 0
    image: str = ""
    network_mode: str = ""
    diagnostics: list[BuildDiagnostic] = Field(default_factory=list)
    output: str = ""
    warnings: list[str] = Field(default_factory=list)


class BuildError(RuntimeError):
    """A rejected or impossible build request, mapped to a structured HTTP error by the route."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class StagingError(BuildError):
    """Raised while walking the workspace or overlaying the proposed patches."""


__all__ = [
    "BuildDiagnostic",
    "BuildError",
    "BuildModel",
    "BuildPatchInput",
    "BuildResult",
    "BuildSeverity",
    "BuildStackId",
    "BuildStatusId",
    "BuildVerifyRequest",
    "BuilderStatus",
    "StagingError",
]
