"""FastAPI + Pydantic + SQLAlchemy 2 vertical-slice generator (Phase 12).

Every slice renders ORM entity -> Pydantic request/response schemas -> repository -> service ->
``APIRouter`` route module (+ pytest skeleton), with the same strict layering as the other stacks:
route modules only see schemas and the service, the service owns the repository, entities stay in
the persistence boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.generators.base import (
    GeneratedFile,
    GeneratorConfig,
    camel_case,
    kebab_case,
    pascal_case,
    plural,
    register,
    render,
    table_name,
    template_environment,
)
from app.models.blueprint import Blueprint, BlueprintStack, SliceSpec

STACK_ID = BlueprintStack.PYTHON_FASTAPI
DISPLAY_NAME = "FastAPI"

_PYTHON_TYPES = {
    "string": "str",
    "text": "str",
    "email": "str",
    "int": "int",
    "integer": "int",
    "long": "int",
    "decimal": "Decimal",
    "bigdecimal": "Decimal",
    "double": "float",
    "float": "float",
    "boolean": "bool",
    "bool": "bool",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
    "instant": "datetime",
    "uuid": "UUID",
}

_TYPE_IMPORTS = {
    "Decimal": "from decimal import Decimal",
    "date": "from datetime import date",
    "datetime": "from datetime import datetime",
    "UUID": "from uuid import UUID",
}

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


@dataclass(frozen=True, slots=True)
class _PythonField:
    name: str
    python_type: str
    required: bool
    sqlalchemy_type: str
    request_type: str
    response_type: str
    field_expression: str


@dataclass(frozen=True, slots=True)
class _Dependency:
    name: str
    var: str
    services_module: str
    schemas_module: str


def _join_path(*parts: str) -> str:
    return "/".join(part.strip("/\\") for part in parts if part)


def _package(base: str) -> str:
    return base.strip().strip(".").replace("/", ".") or "app"


def _package_path(package: str) -> str:
    return package.replace(".", "/")


def _python_type(raw: str) -> str:
    text = (raw or "string").strip()
    return _PYTHON_TYPES.get(text.lower(), text or "str")


def _field_views(spec: SliceSpec) -> tuple[_PythonField, ...]:
    views: list[_PythonField] = []
    for field in spec.fields:
        python_type = _python_type(field.type)
        optional = "" if field.required else " | None"
        views.append(
            _PythonField(
                name=camel_case(field.name),
                python_type=python_type,
                required=field.required,
                sqlalchemy_type=f"{python_type}{optional}",
                request_type=f"{python_type}{optional}",
                response_type=f"{python_type}{optional}",
                field_expression=_field_expression(python_type, field.type, field.required),
            )
        )
    return tuple(views)


def _field_expression(python_type: str, raw_type: str, required: bool) -> str:
    if not required:
        return "Field(default=None)"
    if python_type == "str":
        if (raw_type or "").strip().lower() == "email":
            return f'Field(min_length=3, max_length=254, pattern=r"{_EMAIL_PATTERN}")'
        return "Field(min_length=1, max_length=200)"
    if python_type in {"int", "float", "Decimal"}:
        return "Field(ge=0)"
    return "Field()"


def _imports_for(fields: tuple[_PythonField, ...]) -> tuple[str, ...]:
    names = {field.python_type for field in fields}
    return tuple(_TYPE_IMPORTS[name] for name in _TYPE_IMPORTS if name in names)


class FastApiGenerator:
    stack_id = STACK_ID
    display_name = DISPLAY_NAME

    def generate_slice(self, spec: SliceSpec, config: GeneratorConfig) -> list[GeneratedFile]:
        package = _package(config.base)
        root = _package_path(package)
        name = spec.name
        var = camel_case(pascal_case(spec.name))
        fields = _field_views(spec)
        dependencies = tuple(
            _Dependency(
                name=dependency.name,
                var=camel_case(pascal_case(dependency.name)),
                services_module=f"{package}.services.{camel_case(pascal_case(dependency.name))}_service",
                schemas_module=f"{package}.schemas.{camel_case(pascal_case(dependency.name))}",
            )
            for dependency in config.dependencies_of(spec)
        )
        env = template_environment("fastapi")

        payload = {
            "name": name,
            "var": var,
            "plural": plural(var),
            "route": kebab_case(plural(var)),
            "table": table_name(spec.name),
            "fields": fields,
            "imports": _imports_for(fields),
            "package": package,
            "db_module": f"{package}.db",
            "models_module": f"{package}.models.{var}",
            "schemas_module": f"{package}.schemas.{var}",
            "repositories_module": f"{package}.repositories.{var}_repository",
            "services_module": f"{package}.services.{var}_service",
            "dependencies": dependencies,
            "init_params": _init_params(spec.name, dependencies),
            "init_body": _init_body(dependencies),
        }

        files = [
            GeneratedFile(
                file_path=f"{root}/models/{var}.py",
                content=render(env, "entity.py.j2", **payload),
                summary=f"SQLAlchemy 2 model {name} with {len(fields)} business field(s)",
            ),
            GeneratedFile(
                file_path=f"{root}/schemas/{var}.py",
                content=render(env, "schemas.py.j2", **payload),
                summary=f"Pydantic {name}Request/{name}Response with Field validation",
            ),
            GeneratedFile(
                file_path=f"{root}/repositories/{var}_repository.py",
                content=render(env, "repository.py.j2", **payload),
                summary=f"{name}Repository over a SQLAlchemy Session",
            ),
            GeneratedFile(
                file_path=f"{root}/services/{var}_service.py",
                content=render(env, "service.py.j2", **payload),
                summary=f"{name}Service with constructor-injected repository",
            ),
            GeneratedFile(
                file_path=f"{root}/api/{var}_routes.py",
                content=render(env, "routes.py.j2", **payload),
                summary=f"APIRouter for {name} exposing response DTOs only",
            ),
        ]

        if spec.include_tests:
            files.append(
                GeneratedFile(
                    file_path=f"tests/test_{var}_service.py",
                    content=render(env, "service_test.py.j2", **payload),
                    summary=f"pytest skeleton for {name}Service",
                )
            )
        return files

    def generate_project_files(self, blueprint: Blueprint) -> list[GeneratedFile]:
        package = _package(blueprint.base_package_or_namespace)
        root = _package_path(package)
        env = template_environment("fastapi")
        slices = [
            {
                "var": camel_case(pascal_case(spec.name)),
                "api_module": f"{package}.api.{camel_case(pascal_case(spec.name))}_routes",
            }
            for spec in blueprint.slices
        ]
        payload = {
            "project_name": blueprint.project_name.strip(),
            "slug": kebab_case(blueprint.project_name) or "kodo-app",
            "package_root": f"{package.split('.')[0]}*",
        }

        files = [
            GeneratedFile(
                file_path="pyproject.toml",
                content=render(env, "pyproject.toml.j2", **payload),
                summary="PEP 621 project with FastAPI, Pydantic, SQLAlchemy and dev tools",
            ),
            GeneratedFile(
                file_path=f"{root}/__init__.py",
                content=render(env, "package_init.py.j2", label="Application"),
                summary=f"Python package marker for {package}",
            ),
            GeneratedFile(
                file_path=f"{root}/db.py",
                content=render(env, "db.py.j2"),
                summary="SQLAlchemy declarative base, engine and session factory",
            ),
            GeneratedFile(
                file_path=f"{root}/main.py",
                content=render(env, "main.py.j2", slices=slices, project_name=payload["project_name"]),
                summary="FastAPI app with /health and every slice router included",
            ),
        ]
        for subpackage, label in (
            ("models", "ORM models"),
            ("schemas", "Pydantic schemas"),
            ("repositories", "Repositories"),
            ("services", "Services"),
            ("api", "HTTP routers"),
        ):
            files.append(
                GeneratedFile(
                    file_path=f"{root}/{subpackage}/__init__.py",
                    content=render(env, "package_init.py.j2", label=label),
                    summary=f"Python package marker for {package}.{subpackage}",
                )
            )
        return files


def _init_params(slice_name: str, dependencies: tuple[_Dependency, ...]) -> str:
    params = [f"self, repository: {slice_name}Repository"]
    params.extend(f"{dependency.var}_service: {dependency.name}Service" for dependency in dependencies)
    return ", ".join(params)


def _init_body(dependencies: tuple[_Dependency, ...]) -> list[str]:
    lines = ["self._repository = repository"]
    lines.extend(
        f"self._{dependency.var}_service = {dependency.var}_service" for dependency in dependencies
    )
    return lines


register(FastApiGenerator())

__all__ = ["DISPLAY_NAME", "STACK_ID", "FastApiGenerator"]
