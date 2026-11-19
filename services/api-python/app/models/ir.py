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


class AuditRuleId(StrEnum):
    LAYER_VIOLATION = "LAYER_VIOLATION"
    CIRCULAR_DEPENDENCY = "CIRCULAR_DEPENDENCY"
    GOD_CLASS = "GOD_CLASS"
    ORPHAN_COMPONENT = "ORPHAN_COMPONENT"
    ENTITY_EXPOSED_IN_CONTROLLER = "ENTITY_EXPOSED_IN_CONTROLLER"
    MISSING_VALIDATION = "MISSING_VALIDATION"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class AuditFinding(IrModel):
    id: str
    rule_id: AuditRuleId
    severity: Severity
    title: str
    message: str
    suggestion: str
    node_ids: list[str] = Field(default_factory=list)
    edge_keys: list[str] = Field(default_factory=list)
    file_path: str | None = None


class AuditSummary(IrModel):
    errors: int = 0
    warnings: int = 0
    info: int = 0


class AuditReport(IrModel):
    score: int = Field(default=100, ge=0, le=100)
    summary: AuditSummary = Field(default_factory=AuditSummary)
    findings: list[AuditFinding] = Field(default_factory=list)


class WorkspaceIR(IrModel):
    name: str
    root_path: str
    detected_stacks: list[Stack]
    nodes: list[ComponentNode]
    relations: list[ComponentRelation]
    mermaid_class_diagram: str = ""
    warnings: list[str] = Field(default_factory=list)
    audit: AuditReport = Field(default_factory=AuditReport)
