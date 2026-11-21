"""Stack generator plugin contract, registry and Jinja2 plumbing (Phase 4).

A plugin turns a :class:`~app.models.blueprint.Blueprint` into stack-idiomatic source text in
memory. Nothing in this package touches the filesystem: generated files flow into the normal
``POST /api/v1/scaffold/dry-run`` -> Monaco diff -> guarded ``POST /api/v1/apply`` pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.models.blueprint import Blueprint, BlueprintStack, SliceSpec

TEMPLATE_ROOT = Path(__file__).with_name("templates")

LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".xaml": "xml",
    ".csproj": "xml",
    ".xml": "xml",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".md": "markdown",
    ".properties": "plaintext",
}

_WORD = re.compile(r"[A-Za-z0-9]+")


class GeneratorError(ValueError):
    """A blueprint cannot be rendered (unknown stack, duplicate output path, bad name)."""


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    """One file to create, described relative to the workspace root (POSIX separators)."""

    file_path: str
    content: str
    summary: str

    @property
    def language(self) -> str:
        return language_for_path(self.file_path)


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    """Everything a plugin needs while rendering one slice of a blueprint."""

    project_name: str
    base: str
    slices: tuple[SliceSpec, ...]

    @classmethod
    def from_blueprint(cls, blueprint: Blueprint) -> GeneratorConfig:
        return cls(
            project_name=blueprint.project_name.strip(),
            base=blueprint.base_package_or_namespace.strip().strip("."),
            slices=tuple(blueprint.slices),
        )

    def dependencies_of(self, spec: SliceSpec) -> tuple[SliceSpec, ...]:
        by_name = {slice_spec.name: slice_spec for slice_spec in self.slices}
        return tuple(
            by_name[name] for name in spec.depends_on_slices if name in by_name and name != spec.name
        )


@runtime_checkable
class StackGeneratorPlugin(Protocol):
    """A stack plugin. Implementations stay pure: text in, text out, no I/O."""

    stack_id: BlueprintStack
    display_name: str

    def generate_slice(self, spec: SliceSpec, config: GeneratorConfig) -> list[GeneratedFile]:
        """Render one vertical slice (entity/model, DTO, repository, service, controller, tests)."""

    def generate_project_files(self, blueprint: Blueprint) -> list[GeneratedFile]:
        """Render the minimal project skeleton (build file, entry point, configuration)."""


_REGISTRY: dict[str, StackGeneratorPlugin] = {}


def register(plugin: StackGeneratorPlugin) -> StackGeneratorPlugin:
    _REGISTRY[plugin.stack_id.value] = plugin
    return plugin


def get_plugin(stack_id: str) -> StackGeneratorPlugin:
    plugin = _REGISTRY.get(str(stack_id))
    if plugin is None:
        known = ", ".join(sorted(_REGISTRY)) or "none registered"
        raise GeneratorError(f"Unknown stack '{stack_id}'. Registered generators: {known}.")
    return plugin


def registry() -> dict[str, StackGeneratorPlugin]:
    return dict(_REGISTRY)


def generate_files(blueprint: Blueprint, *, include_project_skeleton: bool) -> list[GeneratedFile]:
    """Render the whole blueprint, rejecting two files that would write the same path."""
    plugin = get_plugin(blueprint.stack.value)
    config = GeneratorConfig.from_blueprint(blueprint)

    files: list[GeneratedFile] = []
    if include_project_skeleton:
        files.extend(plugin.generate_project_files(blueprint))
    for spec in blueprint.slices:
        files.extend(plugin.generate_slice(spec, config))

    seen: set[str] = set()
    duplicates: list[str] = []
    for generated in files:
        key = generated.file_path.lower()
        if key in seen:
            duplicates.append(generated.file_path)
        seen.add(key)
    if duplicates:
        raise GeneratorError(
            "The blueprint would generate the same path twice: "
            + ", ".join(sorted(set(duplicates)))
            + ". Rename the slice or the project."
        )
    return files


@lru_cache(maxsize=8)
def template_environment(folder: str) -> Environment:
    """Jinja2 environment rooted at ``app/generators/templates/<folder>``.

    Autoescaping stays off (source code, not HTML) and unknown variables raise instead of
    rendering empty code — a broken template must fail loudly during development.
    """
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_ROOT / folder)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render(environment: Environment, template_name: str, **context: object) -> str:
    return environment.get_template(template_name).render(**context)


def language_for_path(file_path: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(Path(file_path).suffix.lower(), "plaintext")


def words(value: str) -> list[str]:
    return _WORD.findall(value)


def pascal_case(value: str) -> str:
    parts = words(value)
    if not parts:
        return "Kodo"
    return "".join(part[:1].upper() + part[1:] for part in parts)


def camel_case(value: str) -> str:
    pascal = pascal_case(value)
    return pascal[:1].lower() + pascal[1:]


def kebab_case(value: str) -> str:
    return "-".join(part.lower() for part in words(value)) or "kodo"


def snake_case(value: str) -> str:
    return "_".join(part.lower() for part in words(value)) or "kodo"


def plural(value: str) -> str:
    lowered = value.lower()
    if lowered.endswith("y") and not lowered.endswith(("ay", "ey", "iy", "oy", "uy")):
        return f"{value[:-1]}ies"
    if lowered.endswith(("s", "x", "z", "ch", "sh")):
        return f"{value}es"
    return f"{value}s"


def table_name(value: str) -> str:
    return snake_case(plural(pascal_case(value)))


__all__ = [
    "LANGUAGE_BY_SUFFIX",
    "GeneratedFile",
    "GeneratorConfig",
    "GeneratorError",
    "StackGeneratorPlugin",
    "camel_case",
    "generate_files",
    "get_plugin",
    "kebab_case",
    "language_for_path",
    "pascal_case",
    "plural",
    "register",
    "registry",
    "render",
    "snake_case",
    "table_name",
    "template_environment",
]
