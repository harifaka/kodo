"""Layer and kind classification for Python components (Phase 12).

Pure heuristics over names, base classes, decorators and file locations — identical inputs always
produce the same layer so scans stay diffable.
"""

from __future__ import annotations

import posixpath

from app.models.ir import ComponentField, Layer, NodeKind

CONTROLLER_BASES = frozenset(
    {"APIView", "ViewSet", "ModelViewSet", "GenericAPIView", "View", "MethodView", "Resource"}
)
ORM_BASES = frozenset({"DeclarativeBase", "Base", "Model"})
INTERFACE_BASES = frozenset({"Protocol", "ABC"})
DTO_BASES = frozenset({"BaseModel", "Schema", "Serializer"})
EXCEPTION_BASES = frozenset({"Exception", "BaseException", "ValueError", "RuntimeError"})

_SERVICE_FOLDERS = frozenset({"services", "service", "usecases"})
_REPOSITORY_FOLDERS = frozenset({"repositories", "repository", "repos", "db"})
_CONTROLLER_STEMS = frozenset({"views", "routes", "urls", "endpoints", "controllers"})


def infer_kind(bases: list[str]) -> NodeKind:
    base_set = set(bases)
    if base_set & {"Enum", "IntEnum", "StrEnum", "Flag"}:
        return NodeKind.ENUM
    if base_set & INTERFACE_BASES:
        return NodeKind.INTERFACE
    return NodeKind.CLASS


def infer_layer(
    name: str,
    bases: list[str],
    annotations: list[str],
    rel_path: str,
    fields: list[ComponentField],
) -> Layer:
    base_set = set(bases)
    stem = posixpath.splitext(posixpath.basename(rel_path))[0].lower()
    folder = posixpath.basename(posixpath.dirname(rel_path)).lower()

    if name.endswith(("Controller", "Router", "ViewSet")):
        return Layer.CONTROLLER
    if base_set & CONTROLLER_BASES:
        return Layer.CONTROLLER

    if base_set & ORM_BASES or any(field.annotations == ["@mapped_column"] for field in fields):
        return Layer.ENTITY
    if name.endswith("Entity") or (name.endswith("Model") and not base_set & DTO_BASES):
        return Layer.ENTITY

    if base_set & DTO_BASES or "@dataclass" in annotations or name.endswith(
        ("Dto", "DTO", "Schema", "Request", "Response")
    ):
        return Layer.OTHER

    if base_set & EXCEPTION_BASES or name.endswith(("Error", "Exception")):
        return Layer.OTHER

    if name.endswith(("Service", "UseCase", "Manager")) or folder in _SERVICE_FOLDERS:
        return Layer.SERVICE
    if name.endswith(("Repository", "Repo", "Store", "Dao")) or folder in _REPOSITORY_FOLDERS:
        return Layer.REPOSITORY

    if name.endswith("View") or stem in _CONTROLLER_STEMS:
        return Layer.CONTROLLER
    return Layer.OTHER


__all__ = ["infer_kind", "infer_layer"]
