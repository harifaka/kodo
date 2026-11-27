"""Server-side Mermaid `classDiagram` generation, grouped into architectural layer bands.

Phase 14 turns the flat class dump into a deterministic, presentation-ready diagram:

* every component is mapped into one of seven fixed architectural buckets
  (``UI`` -> ``Controllers`` -> ``Services`` -> ``Repositories`` -> ``Entities`` -> ``DTOs`` -> ``Other``),
  the same order the Macro Graph swimlanes and the Phase 11 layer filter pills use;
* each non-empty bucket becomes a Mermaid ``namespace`` block, classes are sorted inside it and all
  relations are emitted afterwards so a class is declared exactly once;
* ``direction`` and ``member_detail`` keep huge repositories readable.

Everything stays pure and in-memory: this module never touches the filesystem.
"""

from __future__ import annotations

import re
from typing import Literal

from app.analyzers.common import strip_generics
from app.models.ir import (
    ComponentField,
    ComponentMethod,
    ComponentNode,
    ComponentRelation,
)

DiagramDirection = Literal["TB", "LR"]
MemberDetail = Literal["full", "compact", "names_only"]

# Fixed architectural order. The Macro Graph swimlanes use the same sequence.
LAYER_BUCKETS: tuple[str, ...] = (
    "UI",
    "Controllers",
    "Services",
    "Repositories",
    "Entities",
    "DTOs",
    "Other",
)

# Core IR has no dedicated `ui` / `dto` layer, so the buckets roll the layer + kind taxonomy up the
# exact same way `apps/web/src/lib/graphFilter.ts::layerGroupOf` does — both diagrams must agree.
_UI_LAYERS = frozenset({"ui", "view", "viewmodel", "component"})
_UI_KINDS = frozenset({"view", "view_model", "viewmodel", "component"})
_DTO_NAME = re.compile(r"(?:Dto|DTO|Request|Response)$")

MAX_MEMBERS_PER_NODE = 10
MAX_COMPACT_FIELDS = 3
MAX_STEREOTYPES = 2
MAX_MEMBER_LENGTH = 70
_UNSAFE_MEMBER_CHARS = re.compile(r"[{}:;#`~\"\\\[\]]+")
_UNSAFE_STEREOTYPE_CHARS = re.compile(r"[{};#`~\"\\<>]+")
# Python/TS subscripts (`Mapped[str]`, `list[Order]`) are not valid Mermaid member text.
_SUBSCRIPT_CHARS = re.compile(r"\[[^\[\]]*\]")

_RELATION_ARROWS = {
    "inherits": "<|--",
    "implements": "<|..",
    "depends_on": "-->",
    "references": "..>",
}


def layer_bucket(node: ComponentNode) -> str:
    """Deterministically map a component into one of :data:`LAYER_BUCKETS`.

    DTOs win over their Core IR layer because Python/TypeScript payloads are analysed as
    ``other``; the name check keeps every ``*Dto`` / ``*Request`` / ``*Response`` clustered.
    """
    if _DTO_NAME.search(node.name):
        return "DTOs"

    layer = str(node.layer).lower()
    kind = str(node.kind).lower()

    if layer in _UI_LAYERS or kind in _UI_KINDS:
        return "UI"
    if layer == "controller" or kind == "router":
        return "Controllers"
    if layer == "service":
        return "Services"
    if layer == "repository":
        return "Repositories"
    if layer == "entity":
        return "Entities"
    if layer == "dto" or kind == "dto":
        return "DTOs"
    return "Other"


def generate_class_diagram(
    nodes: list[ComponentNode],
    relations: list[ComponentRelation],
    *,
    group_by_layer: bool = True,
    direction: DiagramDirection = "TB",
    member_detail: MemberDetail = "full",
) -> str:
    """Render a Mermaid ``classDiagram`` for a Core IR subset.

    Defaults (grouped, top-to-bottom, full members) match the API schema so existing callers that
    only send ``{ nodes, relations }`` keep working unchanged.
    """
    if not nodes:
        return "classDiagram\n    %% No components discovered in this workspace."

    normalized_direction = _normalize_direction(direction)
    detail = _normalize_member_detail(member_detail)

    ordered = sorted(nodes, key=lambda node: (_bucket_index(node), node.name.lower(), node.id))
    aliases = {node.id: f"C{index}" for index, node in enumerate(ordered)}

    lines = ["classDiagram", f"    direction {normalized_direction}"]

    if group_by_layer:
        for bucket in LAYER_BUCKETS:
            group = [node for node in ordered if layer_bucket(node) == bucket]
            if not group:
                continue
            lines.append(f"    namespace {bucket} {{")
            for node in group:
                lines.extend(_class_lines(node, aliases[node.id], indent="        "))
            lines.append("    }")
    else:
        for node in ordered:
            lines.extend(_class_lines(node, aliases[node.id], indent="    "))

    # Members land after every declaration block, so no class is ever declared twice.
    for node in ordered:
        lines.extend(_member_lines(node, aliases[node.id], detail))

    seen_edges: set[tuple[str, str, str]] = set()
    for relation in sorted(relations, key=lambda r: (r.source_id, r.target_id, str(r.type))):
        source = aliases.get(relation.source_id)
        target = aliases.get(relation.target_id)
        if source is None or target is None or source == target:
            continue
        edge_key = (relation.source_id, relation.target_id, str(relation.type))
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        arrow = _RELATION_ARROWS.get(str(relation.type))
        if arrow:
            lines.append(f"    {source} {arrow} {target}")

    return "\n".join(lines)


def _bucket_index(node: ComponentNode) -> int:
    return LAYER_BUCKETS.index(layer_bucket(node))


def _normalize_direction(direction: str) -> str:
    value = str(direction).strip().upper()
    return value if value in {"TB", "LR"} else "TB"


def _normalize_member_detail(member_detail: str) -> str:
    value = str(member_detail).strip().lower()
    return value if value in {"full", "compact", "names_only"} else "full"


def _class_lines(node: ComponentNode, alias: str, *, indent: str) -> list[str]:
    label = _escape_label(node.name)
    stereotypes = _stereotypes(node)
    if not stereotypes:
        return [f'{indent}class {alias}["{label}"]']

    lines = [f'{indent}class {alias}["{label}"] {{']
    lines.extend(f"{indent}    <<{stereotype}>>" for stereotype in stereotypes)
    lines.append(f"{indent}}}")
    return lines


def _stereotypes(node: ComponentNode) -> list[str]:
    rendered: list[str] = []
    for annotation in node.annotations[:MAX_STEREOTYPES]:
        text = _UNSAFE_STEREOTYPE_CHARS.sub("", annotation)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            rendered.append(text[:MAX_MEMBER_LENGTH])
    return rendered


def _member_lines(node: ComponentNode, alias: str, detail: str) -> list[str]:
    if detail == "names_only":
        return []

    fields = _render_all(node.fields)
    methods = _render_all(node.methods)

    if detail == "compact":
        visible_fields = fields[:MAX_COMPACT_FIELDS]
        summary = _compact_summary(len(fields) - len(visible_fields), len(methods))
        lines = [f"    {alias} : {member}" for member in visible_fields]
        if summary:
            lines.append(f"    {alias} : {summary}")
        return lines

    lines = [f"    {alias} : {member}" for member in fields[:MAX_MEMBERS_PER_NODE]]
    lines.extend(f"    {alias} : {member}" for member in methods[:MAX_MEMBERS_PER_NODE])
    return lines


def _compact_summary(hidden_fields: int, method_count: int) -> str:
    parts: list[str] = []
    if hidden_fields > 0:
        parts.append(f"+{hidden_fields} more field{'s' if hidden_fields != 1 else ''}")
    if method_count > 0:
        parts.append(f"{method_count} method{'s' if method_count != 1 else ''}")
    return ", ".join(parts)


def _render_all(members: list[ComponentField] | list[ComponentMethod]) -> list[str]:
    rendered: list[str] = []
    for member in members:
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
        # Python annotates parameters as `name: Type`; a colon is not valid Mermaid member text,
        # and the whole signature already reads better with names only.
        parameters = ", ".join(
            _clean(_parameter_name(parameter)) for parameter in member.parameters
        )
        return_type = strip_generics(member.return_type or "")
        signature = f"{prefix}{member.name}({parameters})"
        text = f"{signature} {return_type}".strip()

    return _clean(text)


def _parameter_name(parameter: str) -> str:
    """`user: CurrentUser` -> `user` (Java/C# `String name` parameters pass through untouched)."""
    text = _strip_subscripts(strip_generics(parameter))
    head, separator, _ = text.partition(":")
    return head if separator else text


def _visibility_prefix(visibility: str | None) -> str:
    return {
        "public": "+",
        "private": "-",
        "protected": "#",
        "internal": "~",
        "package": "~",
    }.get((visibility or "").lower(), "")


def _clean(text: str) -> str:
    cleaned = _UNSAFE_MEMBER_CHARS.sub("", _strip_subscripts(text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= MAX_MEMBER_LENGTH:
        return cleaned

    clipped = cleaned[:MAX_MEMBER_LENGTH]
    boundary = max(clipped.rfind(" "), clipped.rfind(","), clipped.rfind(")"))
    if boundary > 20:
        clipped = clipped[:boundary]
    return f"{clipped.rstrip(' ,')}…"


def _strip_subscripts(text: str) -> str:
    """`dict[str, Any]` -> `dict` (innermost first, so nested subscripts collapse too)."""
    previous = text
    for _ in range(4):
        current = _SUBSCRIPT_CHARS.sub("", previous)
        if current == previous:
            break
        previous = current
    return previous


def _escape_label(text: str) -> str:
    return text.replace('"', "'").replace("[", "(").replace("]", ")")