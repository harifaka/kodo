"""Node.js / TypeScript layered Express generator."""

from __future__ import annotations

from dataclasses import dataclass

from app.generators.base import (
    GeneratedFile,
    GeneratorConfig,
    camel_case,
    kebab_case,
    register,
    render,
    template_environment,
)
from app.models.blueprint import Blueprint, BlueprintStack, SliceSpec

STACK_ID = BlueprintStack.NODEJS
DISPLAY_NAME = "Node.js (TypeScript)"

# class-validator decorators a generated DTO may import.
_VALIDATORS = frozenset(
    {
        "IsNotEmpty",
        "IsString",
        "IsNumber",
        "IsInt",
        "IsBoolean",
        "IsEmail",
        "IsUUID",
        "IsDateString",
        "IsOptional",
        "IsDefined",
        "IsPositive",
        "Min",
        "Max",
        "Length",
        "Matches",
        "IsArray",
        "ValidateNested",
    }
)

_KIND_BY_TYPE = {
    "string": "string",
    "text": "string",
    "email": "email",
    "int": "int",
    "integer": "int",
    "long": "int",
    "number": "number",
    "decimal": "number",
    "double": "number",
    "float": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "date",
    "datetime": "date",
    "timestamp": "date",
    "uuid": "uuid",
}

_TS_TYPE = {
    "string": "string",
    "email": "string",
    "int": "number",
    "number": "number",
    "boolean": "boolean",
    "date": "string",
    "uuid": "string",
}

_SAMPLE = {
    "string": "'sample'",
    "email": "'user@example.com'",
    "int": "1",
    "number": "1",
    "boolean": "true",
    "date": "'2024-01-01'",
    "uuid": "'00000000-0000-0000-0000-000000000000'",
}


@dataclass(frozen=True, slots=True)
class _NodeField:
    name: str
    ts_type: str
    required: bool
    decorators: tuple[str, ...]
    sample: str


@dataclass(frozen=True, slots=True)
class _NodeContext:
    name: str
    kebab: str
    dto: str
    fields: tuple[_NodeField, ...]
    validator_imports: tuple[str, ...]


def _decorator_name(raw: str) -> str:
    text = raw.strip().lstrip("@").strip()
    return text.split("(", 1)[0].strip().split(".")[-1]


def _decorator(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    return text if text.startswith("@") else f"@{text}"


def _field_views(spec: SliceSpec) -> tuple[_NodeField, ...]:
    views: list[_NodeField] = []
    for field in spec.fields:
        kind = _KIND_BY_TYPE.get((field.type or "string").strip().lower(), "string")
        decorators: list[str] = []

        if kind == "string":
            decorators.append("@IsString()")
        elif kind == "email":
            decorators.extend(["@IsString()", "@IsEmail()"])
        elif kind == "int":
            decorators.extend(["@IsNumber()", "@IsInt()"])
        elif kind == "number":
            decorators.append("@IsNumber()")
        elif kind == "boolean":
            decorators.append("@IsBoolean()")
        elif kind == "date":
            decorators.append("@IsDateString()")
        elif kind == "uuid":
            decorators.append("@IsUUID()")

        decorators.extend(
            _decorator(raw)
            for raw in field.annotations
            if raw.strip() and _decorator_name(raw) in _VALIDATORS
        )

        if not field.required:
            decorators.insert(0, "@IsOptional()")
        elif kind == "string":
            decorators.append("@IsNotEmpty()")
        else:
            decorators.append("@IsDefined()")

        views.append(
            _NodeField(
                name=camel_case(field.name),
                ts_type=_TS_TYPE[kind],
                required=field.required,
                decorators=tuple(dict.fromkeys(decorators)),
                sample=_SAMPLE[kind],
            )
        )
    return tuple(views)


def _slice_context(spec: SliceSpec) -> _NodeContext:
    fields = _field_views(spec)
    names = {_decorator_name(raw) for field in fields for raw in field.decorators}
    return _NodeContext(
        name=spec.name,
        kebab=kebab_case(spec.name),
        dto=f"Create{spec.name}Dto",
        fields=fields,
        validator_imports=tuple(sorted(names & _VALIDATORS)),
    )


class NodeJsGenerator:
    stack_id = STACK_ID
    display_name = DISPLAY_NAME

    def generate_slice(self, spec: SliceSpec, config: GeneratorConfig) -> list[GeneratedFile]:
        context = _slice_context(spec)
        folder = f"src/modules/{context.kebab}"
        name = spec.name
        dependencies = [
            {
                "name": dependency.name,
                "variable": f"{camel_case(dependency.name)}Service",
                "dto": f"{dependency.name}ResponseDto",
                "kebab": kebab_case(dependency.name),
            }
            for dependency in config.dependencies_of(spec)
        ]
        payload = {
            "name": name,
            "lower": name[:1].lower() + name[1:],
            "context": context,
            "fields": context.fields,
            "dependencies": dependencies,
        }
        env = template_environment("nodejs")

        files = [
            GeneratedFile(
                file_path=f"{folder}/{context.kebab}.entity.ts",
                content=render(env, "entity.ts.j2", **payload),
                summary=f"{name}Entity persistence model",
            ),
            GeneratedFile(
                file_path=f"{folder}/{context.kebab}.dto.ts",
                content=render(env, "dto.ts.j2", **payload),
                summary=f"{context.dto} with class-validator constraints + response DTO",
            ),
            GeneratedFile(
                file_path=f"{folder}/{context.kebab}.repository.ts",
                content=render(env, "repository.ts.j2", **payload),
                summary=f"{name}Repository in-memory persistence adapter",
            ),
            GeneratedFile(
                file_path=f"{folder}/{context.kebab}.service.ts",
                content=render(env, "service.ts.j2", **payload),
                summary=f"{name}Service with constructor injection",
            ),
            GeneratedFile(
                file_path=f"{folder}/{context.kebab}.controller.ts",
                content=render(env, "controller.ts.j2", **payload),
                summary=f"{name}Controller using DTOs only",
            ),
        ]

        if spec.include_tests:
            files.append(
                GeneratedFile(
                    file_path=f"{folder}/{context.kebab}.service.spec.ts",
                    content=render(env, "service.spec.ts.j2", **payload),
                    summary=f"{name}Service Vitest skeleton",
                )
            )
        return files

    def generate_project_files(self, blueprint: Blueprint) -> list[GeneratedFile]:
        env = template_environment("nodejs")
        payload = {
            "name": kebab_case(blueprint.project_name) or "kodo-app",
            "project_name": blueprint.project_name.strip(),
        }
        return [
            GeneratedFile(
                file_path="package.json",
                content=render(env, "package.json.j2", **payload),
                summary="npm manifest with express, class-validator and TypeScript",
            ),
            GeneratedFile(
                file_path="tsconfig.json",
                content=render(env, "tsconfig.json.j2", **payload),
                summary="Strict CommonJS TypeScript configuration with decorators",
            ),
            GeneratedFile(
                file_path="src/index.ts",
                content=render(env, "index.ts.j2", **payload),
                summary="Express entry point with a /health route",
            ),
        ]


register(NodeJsGenerator())

__all__ = ["DISPLAY_NAME", "STACK_ID", "NodeJsGenerator"]
