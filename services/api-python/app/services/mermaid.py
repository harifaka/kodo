"""Server-side Mermaid `classDiagram` generation, grouped by architectural layer."""

from __future__ import annotations

import re

from app.analyzers.common import strip_generics
from app.models.ir import ComponentField, ComponentMethod, ComponentNode, ComponentRelation, Layer

LAYER_ORDER: tuple[Layer, ...] = (
    Layer.CONTROLLER,
    Layer.SERVICE,
    Layer.REPOSITORY,
    Layer.ENTITY,
    Layer.VIEWMODEL,
    Layer.VIEW,
    Layer.COMPONENT,
    Layer.OTHER,
)

LAYER_LABELS: dict[Layer, str] = {
    Layer.CONTROLLER: "Controllers",
    Layer.SERVICE: "Services",
    Layer.REPOSITORY: "Repositories",
    Layer.ENTITY: "Entities",
    Layer.VIEWMODEL: "ViewModels",
    Layer.VIEW: "Views",
    Layer.COMPONENT: "Components",
    Layer.OTHER: "Other",
}

_RELATION_ARROWS = {
    "inherits": "<|--",
    "implements": "<|..",
    "depends_on": "-->",
    "references": "..>",
}

MAX_MEMBERS_PER_NODE = 10
MAX_MEMBER_LENGTH = 70
_UNSAFE_MEMBER_CHARS = re.compile(r"[{};#`~\"\\]+")


def generate_class_diagram(
    nodes: list[ComponentNode],
    relations: list[ComponentRelation],
) -> str:
    if not nodes:
        return "classDiagram\n    %% No components discovered in this workspace."

    ordered = sorted(nodes, key=lambda n: (LAYER_ORDER.index(n.layer), n.name.lower(), n.id))
    aliases = {node.id: f"C{index}" for index, node in enumerate(ordered)}

    lines = ["classDiagram", "    direction LR"]

    for layer in LAYER_ORDER:
        group = [node for node in ordered if node.layer == layer]
        if not group:
            continue
        lines.append(f"    namespace {LAYER_LABELS[layer]} {{")
        for node in group:
            lines.append(f'        class {aliases[node.id]}["{_escape_label(node.name)}"]')
        lines.append("    }")

    for node in ordered:
        alias = aliases[node.id]
        for member in _members(node.fields):
            lines.append(f"    {alias} : {member}")
        for member in _members(node.methods):
            lines.append(f"    {alias} : {member}")

    for relation in relations:
        source = aliases.get(relation.source_id)
        target = aliases.get(relation.target_id)
        if source is None or target is None or source == target:
            continue
        arrow = _RELATION_ARROWS.get(str(relation.type))
        if arrow:
            lines.append(f"    {source} {arrow} {target}")

    return "\n".join(lines)


def _members(members: list[ComponentField] | list[ComponentMethod]) -> list[str]:
    rendered: list[str] = []
    for member in members[:MAX_MEMBERS_PER_NODE]:
        text = _render_member(member)
        if text:
            rendered.append(text)
    return rendered


def _render_member(member: ComponentField | ComponentMethod) -> str:
    if isinstance(member, ComponentField):
        prefix = _visibility_prefix(member.visibility)
        text = f"{prefix}{strip_generics(member.type)} {member.name}".strip()
    else:
        prefix = "+"
        parameters = ", ".join(_clean(strip_generics(parameter)) for parameter in member.parameters)
        return_type = strip_generics(member.return_type or "")
        signature = f"{prefix}{member.name}({parameters})"
        text = f"{signature} {return_type}".strip()

    return _clean(text)


def _visibility_prefix(visibility: str | None) -> str:
    return {
        "public": "+",
        "private": "-",
        "protected": "#",
        "internal": "~",
        "package": "~",
    }.get((visibility or "").lower(), "")


def _clean(text: str) -> str:
    cleaned = _UNSAFE_MEMBER_CHARS.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:MAX_MEMBER_LENGTH]


def _escape_label(text: str) -> str:
    return text.replace('"', "'").replace("[", "(").replace("]", ")")
