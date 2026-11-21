"""C# .NET 8 WPF MVVM generator."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.generators.base import (
    GeneratedFile,
    GeneratorConfig,
    camel_case,
    pascal_case,
    register,
    render,
    template_environment,
)
from app.models.blueprint import Blueprint, BlueprintStack, SliceSpec

STACK_ID = BlueprintStack.CSHARP_WPF
DISPLAY_NAME = "C# WPF (MVVM)"

_CS_TYPES = {
    "string": "string",
    "text": "string",
    "email": "string",
    "int": "int",
    "integer": "int",
    "long": "long",
    "number": "decimal",
    "decimal": "decimal",
    "double": "double",
    "float": "double",
    "boolean": "bool",
    "bool": "bool",
    "date": "DateTime",
    "datetime": "DateTime",
    "timestamp": "DateTime",
    "uuid": "Guid",
}

# System.ComponentModel.DataAnnotations attributes a generated model may carry.
_DATA_ANNOTATIONS = frozenset(
    {
        "Required",
        "StringLength",
        "MaxLength",
        "MinLength",
        "Range",
        "RegularExpression",
        "EmailAddress",
        "Key",
        "Display",
        "DisplayName",
    }
)


@dataclass(frozen=True, slots=True)
class _CsField:
    name: str
    cs_type: str
    is_string: bool
    required: bool
    annotations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CsContext:
    name: str
    model: str
    interface: str
    fields: tuple[_CsField, ...]
    uses_data_annotations: bool


def _attribute_name(raw: str) -> str:
    text = raw.strip().lstrip("[").rstrip("]").strip()
    return text.split("(", 1)[0].strip().split(".")[-1]


def _attribute(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if not text.startswith("["):
        text = f"[{text}]"
    return text


def _assembly_name(project_name: str) -> str:
    raw = project_name.strip()
    if "." in raw:
        parts = [pascal_case(segment) for segment in raw.split(".") if segment.strip()]
        name = ".".join(parts) or "KodoApp"
    else:
        name = pascal_case(raw) or "KodoApp"
    name = re.sub(r"[^A-Za-z0-9.]", "", name)
    return name if name and name[0].isalpha() else f"Kodo{name}"


def _field_views(spec: SliceSpec) -> tuple[_CsField, ...]:
    views: list[_CsField] = []
    for field in spec.fields:
        cs_type = _CS_TYPES.get((field.type or "string").strip().lower(), "string")
        is_string = cs_type == "string"
        annotations = [
            _attribute(raw)
            for raw in field.annotations
            if raw.strip() and _attribute_name(raw) in _DATA_ANNOTATIONS
        ]
        if field.required and not any(_attribute_name(raw) == "Required" for raw in annotations):
            annotations.insert(0, "[Required]")
        if is_string and not any(_attribute_name(raw) == "StringLength" for raw in annotations):
            annotations.append("[StringLength(200)]")

        views.append(
            _CsField(
                name=pascal_case(field.name),
                cs_type=cs_type,
                is_string=is_string,
                required=field.required,
                annotations=tuple(annotations),
            )
        )
    return tuple(views)


def _slice_context(spec: SliceSpec) -> _CsContext:
    fields = _field_views(spec)
    return _CsContext(
        name=spec.name,
        model=f"{spec.name}Model",
        interface=f"I{spec.name}Service",
        fields=fields,
        uses_data_annotations=any(field.annotations for field in fields),
    )


class CSharpWpfGenerator:
    stack_id = STACK_ID
    display_name = DISPLAY_NAME

    def generate_slice(self, spec: SliceSpec, config: GeneratorConfig) -> list[GeneratedFile]:
        context = _slice_context(spec)
        name = spec.name
        dependencies = [
            {
                "name": dependency.name,
                "variable": f"{camel_case(dependency.name)}Service",
                "model": f"{dependency.name}Model",
                "interface": f"I{dependency.name}Service",
            }
            for dependency in config.dependencies_of(spec)
        ]
        payload = {
            "namespace": config.base,
            "name": name,
            "lower": name[:1].lower() + name[1:],
            "camel_name": camel_case(name),
            "context": context,
            "fields": context.fields,
            "dependencies": dependencies,
        }
        env = template_environment("csharp_wpf")

        files = [
            GeneratedFile(
                file_path=f"Models/{context.model}.cs",
                content=render(env, "model.cs.j2", **payload),
                summary=f"{context.model} with DataAnnotations validation",
            ),
            GeneratedFile(
                file_path=f"Services/{context.interface}.cs",
                content=render(env, "service_interface.cs.j2", **payload),
                summary=f"{context.interface} service contract",
            ),
            GeneratedFile(
                file_path=f"Services/{name}Service.cs",
                content=render(env, "service.cs.j2", **payload),
                summary=f"{name}Service implementation with constructor injection",
            ),
            GeneratedFile(
                file_path=f"ViewModels/{name}ViewModel.cs",
                content=render(env, "viewmodel.cs.j2", **payload),
                summary=f"{name}ViewModel using CommunityToolkit.Mvvm",
            ),
            GeneratedFile(
                file_path=f"Views/{name}View.xaml",
                content=render(env, "view.xaml.j2", **payload),
                summary=f"{name}View XAML bound to the view model",
            ),
            GeneratedFile(
                file_path=f"Views/{name}View.xaml.cs",
                content=render(env, "view.xaml.cs.j2", **payload),
                summary=f"{name}View code-behind receiving the view model",
            ),
        ]

        if spec.include_tests:
            files.append(
                GeneratedFile(
                    file_path=f"Tests/{name}ServiceTests.cs",
                    content=render(env, "service_tests.cs.j2", **payload),
                    summary=f"{name}ServiceTests xUnit skeleton",
                )
            )
        return files

    def generate_project_files(self, blueprint: Blueprint) -> list[GeneratedFile]:
        namespace = blueprint.base_package_or_namespace.strip().strip(".")
        assembly = _assembly_name(blueprint.project_name)
        env = template_environment("csharp_wpf")
        payload = {
            "namespace": namespace,
            "assembly": assembly,
            "project_name": blueprint.project_name.strip(),
        }
        return [
            GeneratedFile(
                file_path=f"{assembly}.csproj",
                content=render(env, "project.csproj.j2", **payload),
                summary="WPF net8.0-windows project with CommunityToolkit.Mvvm",
            ),
            GeneratedFile(
                file_path="App.xaml",
                content=render(env, "app.xaml.j2", **payload),
                summary="WPF application definition",
            ),
            GeneratedFile(
                file_path="App.xaml.cs",
                content=render(env, "app.xaml.cs.j2", **payload),
                summary="WPF application entry point",
            ),
        ]


register(CSharpWpfGenerator())

__all__ = ["DISPLAY_NAME", "STACK_ID", "CSharpWpfGenerator"]
