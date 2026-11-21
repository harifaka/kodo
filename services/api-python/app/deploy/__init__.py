"""Phase 6 Deploy Studio: Docker artifact generation, local Docker control and Git export.

Nothing in this package writes workspace files directly. Generated artifacts are returned as
``DryRunResponse`` patches and reach disk only through the guarded ``/api/v1/apply`` pipeline.
"""

from app.deploy.errors import DeployError
from app.deploy.generator import (
    BACKING_SERVICES,
    STACKS,
    DeployArtifacts,
    detect_stack,
    generate_artifacts,
)
from app.deploy.studio_service import build_deploy_plan

__all__ = [
    "BACKING_SERVICES",
    "STACKS",
    "DeployArtifacts",
    "DeployError",
    "build_deploy_plan",
    "detect_stack",
    "generate_artifacts",
]
