"""HTTP surface of the DeepSeek Architecture Copilot (Phase 5).

All three workflows are read-only: they return reviewed-in-the-UI ``DryRunResponse`` patches or a
blueprint for human review. Nothing here writes to the workspace or persists an API key.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.llm.client import LlmClient
from app.llm.config import LlmOverride, is_local_base_url, resolve_config
from app.llm.errors import LlmError
from app.llm.workflows import (
    AiPatchResult,
    SpecBlueprintResult,
    audit_fix,
    implement_method,
    spec_to_blueprint,
)
from app.models.blueprint import Blueprint, BlueprintStack
from app.models.ir import AuditFinding, WorkspaceIR
from app.patching.models import DryRunResponse
from app.patching.paths import PatchRejected

router = APIRouter()


class AiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SpecToBlueprintRequest(AiModel):
    spec: str = Field(..., min_length=8, max_length=20_000)
    stack: BlueprintStack
    project_name: str | None = Field(default=None, max_length=80)
    base_package_or_namespace: str | None = Field(default=None, max_length=160)
    llm_config: LlmOverride | None = None


class SpecToBlueprintResponse(AiModel):
    blueprint: Blueprint
    rationale: str
    model_used: str
    warnings: list[str] = Field(default_factory=list)


class AuditFixRequest(AiModel):
    root_path: str = Field(..., min_length=1)
    finding: AuditFinding
    workspace_ir: WorkspaceIR
    llm_config: LlmOverride | None = None


class ImplementMethodRequest(AiModel):
    root_path: str = Field(..., min_length=1)
    file_path: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)
    method_name: str = Field(..., min_length=1, max_length=200)
    instruction: str = Field(..., min_length=1, max_length=4_000)
    workspace_ir: WorkspaceIR
    llm_config: LlmOverride | None = None


class AiPatchResponse(DryRunResponse):
    explanation: str
    model_used: str


class TestConnectionRequest(AiModel):
    llm_config: LlmOverride | None = None


class TestConnectionResponse(AiModel):
    ok: bool
    provider: str
    base_url: str
    code_model: str
    reasoning_model: str
    models: list[str] = Field(default_factory=list)


def _client(override: LlmOverride | None) -> LlmClient:
    return LlmClient(resolve_config(override))


def _fail(exc: LlmError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.payload())


def _reject(exc: PatchRejected) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": "PATH_REJECTED", "message": str(exc)})


def _patch_response(result: AiPatchResult) -> AiPatchResponse:
    return AiPatchResponse(
        patches=result.response.patches,
        warnings=result.response.warnings,
        explanation=result.explanation,
        model_used=result.model_used,
    )


@router.post("/api/v1/ai/spec-to-blueprint", response_model=SpecToBlueprintResponse, tags=["ai"])
async def spec_to_blueprint_route(request: SpecToBlueprintRequest) -> SpecToBlueprintResponse:
    """Turn a business spec into a validated blueprint for human review in the Builder."""
    try:
        result: SpecBlueprintResult = await spec_to_blueprint(
            spec=request.spec,
            stack=request.stack,
            project_name=request.project_name,
            base_package=request.base_package_or_namespace,
            client=_client(request.llm_config),
        )
    except LlmError as exc:
        raise _fail(exc) from exc

    return SpecToBlueprintResponse(
        blueprint=result.blueprint,
        rationale=result.rationale,
        model_used=result.model_used,
        warnings=result.warnings,
    )


@router.post("/api/v1/ai/audit-fix", response_model=AiPatchResponse, tags=["ai"])
async def audit_fix_route(request: AuditFixRequest) -> AiPatchResponse:
    """Propose a fix for one audit finding. Read-only: the response is a normal dry-run plan."""
    try:
        result = await audit_fix(
            root_path=request.root_path,
            finding=request.finding,
            workspace_ir=request.workspace_ir,
            client=_client(request.llm_config),
        )
    except PatchRejected as exc:
        raise _reject(exc) from exc
    except LlmError as exc:
        raise _fail(exc) from exc

    return _patch_response(result)


@router.post("/api/v1/ai/implement-method", response_model=AiPatchResponse, tags=["ai"])
async def implement_method_route(request: ImplementMethodRequest) -> AiPatchResponse:
    """Implement one method inside a known file. Read-only: the result opens in the diff preview."""
    try:
        result = await implement_method(
            root_path=request.root_path,
            file_path=request.file_path,
            node_id=request.node_id,
            method_name=request.method_name,
            instruction=request.instruction,
            workspace_ir=request.workspace_ir,
            client=_client(request.llm_config),
        )
    except PatchRejected as exc:
        raise _reject(exc) from exc
    except LlmError as exc:
        raise _fail(exc) from exc

    return _patch_response(result)


@router.post("/api/v1/ai/test-connection", response_model=TestConnectionResponse, tags=["ai"])
async def test_connection(request: TestConnectionRequest) -> TestConnectionResponse:
    """Minimal ``GET /models`` probe for the settings drawer (DeepSeek Cloud or local Ollama/vLLM)."""
    cfg = resolve_config(request.llm_config)
    try:
        models = await LlmClient(cfg).list_models()
    except LlmError as exc:
        raise _fail(exc) from exc

    return TestConnectionResponse(
        ok=True,
        provider="local" if is_local_base_url(cfg.base_url) else "cloud",
        base_url=cfg.base_url,
        code_model=cfg.code_model,
        reasoning_model=cfg.reasoning_model,
        models=models[:50],
    )


__all__ = ["router"]
