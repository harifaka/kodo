"""Versioned ``kodo.blueprint.json`` contract (Phase 4).

A blueprint is the versionable description of a multi-service project: the target stack, the
base package/namespace and the vertical slices (domain model + dependencies). It is rendered by
the stack generator plugins and saved back into the repository for review alongside the code.

Wire format is camelCase (``schemaVersion``, ``basePackageOrNamespace``, ``dependsOnSlices``);
Python attributes stay snake_case. Mirrors ``packages/core-ir/blueprint.schema.json``.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

BLUEPRINT_FILE_NAME = "kodo.blueprint.json"
BLUEPRINT_SCHEMA_VERSION = "1.0"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")


class BlueprintModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class BlueprintStack(StrEnum):
    SPRING_BOOT = "spring-boot"
    CSHARP_WPF = "csharp-wpf"
    NODEJS = "nodejs"


class BlueprintField(BlueprintModel):
    name: str = Field(..., min_length=1, max_length=60)
    type: str = Field(default="string", max_length=80)
    required: bool = True
    annotations: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("name")
    @classmethod
    def _identifier(cls, value: str) -> str:
        name = value.strip()
        if not _IDENTIFIER.match(name):
            raise ValueError(
                f"Field name '{value}' must start with a letter or underscore and contain only letters, digits or underscores."
            )
        return name


class SliceSpec(BlueprintModel):
    name: str = Field(..., min_length=1, max_length=60)
    fields: list[BlueprintField] = Field(default_factory=list, max_length=60)
    depends_on_slices: list[str] = Field(default_factory=list, max_length=20)
    include_tests: bool = True

    @field_validator("name")
    @classmethod
    def _pascal(cls, value: str) -> str:
        name = value.strip()
        if not _PASCAL.match(name):
            raise ValueError(
                f"Slice name '{value}' must be PascalCase (start with an uppercase letter, letters and digits only)."
            )
        return name

    @field_validator("fields")
    @classmethod
    def _unique_fields(cls, fields: list[BlueprintField]) -> list[BlueprintField]:
        seen: set[str] = set()
        for field in fields:
            if field.name.lower() in seen:
                raise ValueError(f"Duplicate field name '{field.name}' in one slice.")
            seen.add(field.name.lower())
        return fields

    @field_validator("depends_on_slices")
    @classmethod
    def _clean_dependencies(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in values:
            name = raw.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            cleaned.append(name)
        return cleaned

    @model_validator(mode="after")
    def _no_self_dependency(self) -> SliceSpec:
        if self.name in self.depends_on_slices:
            raise ValueError(f"Slice '{self.name}' cannot depend on itself.")
        return self


class Blueprint(BlueprintModel):
    schema_version: str = BLUEPRINT_SCHEMA_VERSION
    project_name: str = Field(..., min_length=1, max_length=80)
    stack: BlueprintStack
    base_package_or_namespace: str = Field(..., min_length=1, max_length=160)
    slices: list[SliceSpec] = Field(default_factory=list, max_length=40)

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: str) -> str:
        if value != BLUEPRINT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported blueprint schemaVersion '{value}'; this Kodo build supports "
                f"'{BLUEPRINT_SCHEMA_VERSION}'."
            )
        return value

    @model_validator(mode="after")
    def _slices_are_consistent(self) -> Blueprint:
        names = [slice_spec.name for slice_spec in self.slices]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Duplicate slice name(s): {', '.join(duplicates)}.")

        known = set(names)
        unknown = sorted(
            {
                dependency
                for slice_spec in self.slices
                for dependency in slice_spec.depends_on_slices
                if dependency not in known
            }
        )
        if unknown:
            raise ValueError(
                f"dependsOnSlices references unknown slice(s): {', '.join(unknown)}. "
                "Define the slice first or remove the dependency."
            )
        return self

    def to_document(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, mode="json")

    def render(self) -> str:
        """Deterministic JSON text committed next to the code (2-space indent + trailing newline)."""
        return json.dumps(self.to_document(), indent=2, ensure_ascii=False) + "\n"


def blueprint_path(root: Path) -> Path:
    return root / BLUEPRINT_FILE_NAME


def load_blueprint(root: Path) -> tuple[bool, Blueprint | None, list[str]]:
    """Read ``kodo.blueprint.json`` from ``root``.

    Returns ``(exists, blueprint, warnings)``. A malformed or unsupported file degrades to
    ``exists=True, blueprint=None`` plus a human-readable warning — never an exception.
    """
    path = blueprint_path(root)
    if not path.is_file():
        return False, None, []

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return True, None, [f"{BLUEPRINT_FILE_NAME} could not be read: {exc}"]

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        return True, None, [
            (
                f"{BLUEPRINT_FILE_NAME} is not valid JSON ({exc.msg} at line {exc.lineno}); "
                "fix it or rebuild the blueprint in the Builder."
            )
        ]

    if not isinstance(document, dict):
        return True, None, [f"{BLUEPRINT_FILE_NAME} must contain a JSON object."]

    try:
        return True, Blueprint.model_validate(document), []
    except ValueError as exc:
        return True, None, [f"{BLUEPRINT_FILE_NAME} does not match schema {BLUEPRINT_SCHEMA_VERSION}: {exc}"]


__all__ = [
    "BLUEPRINT_FILE_NAME",
    "BLUEPRINT_SCHEMA_VERSION",
    "Blueprint",
    "BlueprintField",
    "BlueprintStack",
    "SliceSpec",
    "blueprint_path",
    "load_blueprint",
]
