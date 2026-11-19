"""Core IR — the canonical contract shared with the C# analyzer and the React UI.

Mirrors packages/core-ir/schema.json. Wire format is camelCase; Python attributes stay snake_case.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class IrModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Stack(StrEnum):
    SPRING_BOOT = "spring-boot"
    CSHARP_DOTNET = "csharp-dotnet"
    NODEJS = "nodejs"
    UNKNOWN = "unknown"


class Layer(StrEnum):
    CONTROLLER = "controller"
    SERVICE = "service"
    REPOSITORY = "repository"
    ENTITY = "entity"
    VIEWMODEL = "viewmodel"
    VIEW = "view"
    COMPONENT = "component"
    OTHER = "other"


class NodeKind(StrEnum):
    CLASS = "class"
    INTERFACE = "interface"
    RECORD = "record"
    ENUM = "enum"
    MODULE = "module"


class RelationType(StrEnum):
    DEPENDS_ON = "depends_on"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    REFERENCES = "references"


class ComponentField(IrModel):
    name: str
    type: str
    visibility: str | None = None
    annotations: list[str] = Field(default_factory=list)


class ComponentMethod(IrModel):
    name: str
    return_type: str | None = None
    parameters: list[str] = Field(default_factory=list)


class ComponentNode(IrModel):
    id: str
    name: str
    stack: Stack
    layer: Layer
    kind: NodeKind
    file_path: str
    annotations: list[str] = Field(default_factory=list)
    fields: list[ComponentField] = Field(default_factory=list)
    methods: list[ComponentMethod] = Field(default_factory=list)


class ComponentRelation(IrModel):
    source_id: str
    target_id: str
    type: RelationType


class WorkspaceIR(IrModel):
    name: str
    root_path: str
    detected_stacks: list[Stack]
    nodes: list[ComponentNode]
    relations: list[ComponentRelation]
    mermaid_class_diagram: str = ""
    warnings: list[str] = Field(default_factory=list)
