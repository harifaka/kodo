"""Spring Boot 3 / Java 21 vertical-slice generator.

Every slice renders entity -> DTO -> mapper -> repository -> service -> controller (+ test), with
strict layering: the controller only ever sees DTOs and the service, never the entity or repository.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.generators.base import (
    GeneratedFile,
    GeneratorConfig,
    camel_case,
    kebab_case,
    pascal_case,
    register,
    render,
    table_name,
    template_environment,
)
from app.models.blueprint import Blueprint, BlueprintStack, SliceSpec

STACK_ID = BlueprintStack.SPRING_BOOT
DISPLAY_NAME = "Spring Boot"

_JAVA_TYPES = {
    "string": "String",
    "text": "String",
    "email": "String",
    "int": "Integer",
    "integer": "Integer",
    "long": "Long",
    "decimal": "BigDecimal",
    "bigdecimal": "BigDecimal",
    "double": "Double",
    "float": "Float",
    "boolean": "Boolean",
    "bool": "Boolean",
    "date": "LocalDate",
    "datetime": "LocalDateTime",
    "timestamp": "Instant",
    "instant": "Instant",
    "uuid": "UUID",
}

_IMPORTS = {
    "BigDecimal": "java.math.BigDecimal",
    "LocalDate": "java.time.LocalDate",
    "LocalDateTime": "java.time.LocalDateTime",
    "Instant": "java.time.Instant",
    "UUID": "java.util.UUID",
}

# Jakarta Bean Validation constraints a generated DTO may safely import.
_CONSTRAINTS = frozenset(
    {
        "NotNull",
        "NotBlank",
        "NotEmpty",
        "Size",
        "Min",
        "Max",
        "Pattern",
        "Email",
        "Positive",
        "PositiveOrZero",
        "Negative",
        "NegativeOrZero",
        "Past",
        "Future",
        "DecimalMin",
        "DecimalMax",
        "Digits",
        "Valid",
    }
)


@dataclass(frozen=True, slots=True)
class _JavaField:
    name: str
    accessor: str
    column: str
    java_type: str
    required: bool
    dto_annotations: tuple[str, ...]
    entity_annotations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SliceContext:
    name: str
    table: str
    route: str
    fields: tuple[_JavaField, ...]
    entity_imports: tuple[str, ...]
    dto_constraints: tuple[str, ...]
    dto_imports: tuple[str, ...]
    dto_components: tuple[str, ...]


def _join_path(*parts: str) -> str:
    return "/".join(part.strip("/\\") for part in parts if part)


def _package_path(base: str) -> str:
    return base.replace(".", "/")


def _java_type(raw: str) -> str:
    text = (raw or "string").strip()
    return _JAVA_TYPES.get(text.lower(), text or "String")


def _annotation(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    return text if text.startswith("@") else f"@{text}"


def _annotation_name(raw: str) -> str:
    text = raw.strip().lstrip("@").strip()
    return text.split("(", 1)[0].strip().split(".")[-1]


def _field_views(spec: SliceSpec) -> tuple[_JavaField, ...]:
    views: list[_JavaField] = []
    for field in spec.fields:
        java_type = _java_type(field.type)
        rendered = [_annotation(raw) for raw in field.annotations if raw.strip()]
        constraints = [raw for raw in rendered if _annotation_name(raw) in _CONSTRAINTS]
        if field.required and not constraints:
            constraints.append("@NotBlank" if java_type == "String" else "@NotNull")

        entity_annotations = [
            raw
            for raw in rendered
            if _annotation_name(raw) not in {"NotNull", "NotBlank", "NotEmpty", "Valid"}
        ]
        if not any(_annotation_name(raw) == "Column" for raw in entity_annotations):
            entity_annotations.append(
                f'@Column(name = "{field.name}", nullable = {str(not field.required).lower()})'
            )

        name = camel_case(field.name)
        views.append(
            _JavaField(
                name=name,
                accessor=pascal_case(name),
                column=field.name,
                java_type=java_type,
                required=field.required,
                dto_annotations=tuple(constraints),
                entity_annotations=tuple(entity_annotations),
            )
        )
    return tuple(views)


def _slice_context(spec: SliceSpec) -> _SliceContext:
    fields = _field_views(spec)
    entity_imports = tuple(
        sorted({_IMPORTS[field.java_type] for field in fields if field.java_type in _IMPORTS})
    )
    constraints = tuple(
        sorted({_annotation_name(raw) for field in fields for raw in field.dto_annotations})
    )
    validation_imports = tuple(
        "jakarta.validation.Valid" if name == "Valid" else f"jakarta.validation.constraints.{name}"
        for name in constraints
    )
    return _SliceContext(
        name=spec.name,
        table=table_name(spec.name),
        route=f"/api/{kebab_case(spec.name)}s",
        fields=fields,
        entity_imports=entity_imports,
        dto_constraints=constraints,
        dto_imports=(*validation_imports, *entity_imports),
        dto_components=(
            "Long id",
            *(
                f"{' '.join(field.dto_annotations)} {field.java_type} {field.name}".strip()
                for field in fields
            ),
        ),
    )


def _dependencies(spec: SliceSpec, config: GeneratorConfig) -> list[dict[str, str]]:
    return [
        {
            "name": dependency.name,
            "variable": f"{camel_case(dependency.name)}Service",
            "dto": f"{dependency.name}Dto",
        }
        for dependency in config.dependencies_of(spec)
    ]


class SpringBootGenerator:
    stack_id = STACK_ID
    display_name = DISPLAY_NAME

    def generate_slice(self, spec: SliceSpec, config: GeneratorConfig) -> list[GeneratedFile]:
        context = _slice_context(spec)
        base = config.base
        root = _join_path("src/main/java", _package_path(base))
        dependencies = _dependencies(spec, config)
        env = template_environment("spring_boot")
        name = spec.name

        payload = {
            "base": base,
            "name": name,
            "lower": name[:1].lower() + name[1:],
            "context": context,
            "fields": context.fields,
            "dependencies": dependencies,
        }

        files = [
            GeneratedFile(
                file_path=f"{root}/entity/{name}Entity.java",
                content=render(env, "entity.java.j2", **payload),
                summary=f"JPA entity {name}Entity with {len(context.fields)} business field(s)",
            ),
            GeneratedFile(
                file_path=f"{root}/dto/{name}Dto.java",
                content=render(env, "dto.java.j2", **payload),
                summary=f"Java record {name}Dto with Bean Validation constraints",
            ),
            GeneratedFile(
                file_path=f"{root}/mapper/{name}Mapper.java",
                content=render(env, "mapper.java.j2", **payload),
                summary=f"{name}Mapper mapping entity <-> DTO",
            ),
            GeneratedFile(
                file_path=f"{root}/repository/{name}Repository.java",
                content=render(env, "repository.java.j2", **payload),
                summary=f"{name}Repository extending JpaRepository",
            ),
            GeneratedFile(
                file_path=f"{root}/service/{name}Service.java",
                content=render(env, "service.java.j2", **payload),
                summary=f"{name}Service with constructor injection",
            ),
            GeneratedFile(
                file_path=f"{root}/controller/{name}Controller.java",
                content=render(env, "controller.java.j2", **payload),
                summary=f"{name}Controller exposing DTOs only",
            ),
        ]

        if spec.include_tests:
            files.append(
                GeneratedFile(
                    file_path=f"{_join_path('src/test/java', _package_path(base))}/service/{name}ServiceTest.java",
                    content=render(env, "service_test.java.j2", **payload),
                    summary=f"{name}ServiceTest JUnit 5 + Mockito skeleton",
                )
            )
        return files

    def generate_project_files(self, blueprint: Blueprint) -> list[GeneratedFile]:
        base = blueprint.base_package_or_namespace.strip().strip(".")
        application = f"{pascal_case(blueprint.project_name)}Application"
        artifact = kebab_case(blueprint.project_name) or "kodo-app"
        group = base if "." in base else "com.example"
        env = template_environment("spring_boot")
        payload = {
            "base": base,
            "application": application,
            "artifact": artifact,
            "group": group,
            "project_name": blueprint.project_name.strip(),
        }
        return [
            GeneratedFile(
                file_path="pom.xml",
                content=render(env, "pom.xml.j2", **payload),
                summary="Maven build with spring-boot-starter-web/data-jpa/validation",
            ),
            GeneratedFile(
                file_path=f"{_join_path('src/main/java', _package_path(base))}/{application}.java",
                content=render(env, "application.java.j2", **payload),
                summary=f"Spring Boot entry point {application}",
            ),
            GeneratedFile(
                file_path="src/main/resources/application.yml",
                content=render(env, "application.yml.j2", **payload),
                summary="Application configuration with in-memory H2 datasource",
            ),
        ]


register(SpringBootGenerator())

__all__ = ["DISPLAY_NAME", "STACK_ID", "SpringBootGenerator"]
