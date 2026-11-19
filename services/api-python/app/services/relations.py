"""Resolve parser-level reference candidates into Core IR relations."""

from __future__ import annotations

from collections.abc import Iterable

from app.analyzers.common import BASE_RELATION, ReferenceCandidate
from app.models.ir import ComponentNode, ComponentRelation, NodeKind, RelationType

_RELATION_PRIORITY = {"inherits": 0, "implements": 0, "depends_on": 1, "references": 2}


def resolve_relations(
    nodes: list[ComponentNode],
    references: Iterable[ReferenceCandidate],
) -> list[ComponentRelation]:
    by_id = {node.id: node for node in nodes}
    by_name: dict[str, ComponentNode] = {}
    ambiguous: set[str] = set()
    by_file: dict[str, list[ComponentNode]] = {}

    for node in nodes:
        if node.name in by_name:
            ambiguous.add(node.name)
        by_name[node.name] = node
        by_file.setdefault(node.file_path, []).append(node)

    for name in ambiguous:
        by_name.pop(name, None)

    resolved: list[ComponentRelation] = []
    for reference in references:
        target = _resolve_target(reference, by_id, by_name, by_file)
        if target is None or target.id == reference.source_id:
            continue

        relationship = _relation_type(reference.relation, by_id.get(reference.source_id), target)
        if relationship is None:
            continue

        resolved.append(
            ComponentRelation(source_id=reference.source_id, target_id=target.id, type=relationship)
        )

    return merge_relations(resolved)


def _resolve_target(
    reference: ReferenceCandidate,
    by_id: dict[str, ComponentNode],
    by_name: dict[str, ComponentNode],
    by_file: dict[str, list[ComponentNode]],
) -> ComponentNode | None:
    if reference.file_hint:
        candidates = by_file.get(reference.file_hint, [])
        if not candidates:
            return None
        if reference.target_name:
            for candidate in candidates:
                if candidate.name == reference.target_name:
                    return candidate
        return candidates[0]

    exact = by_id.get(reference.target_name)
    if exact is not None:
        return exact
    return by_name.get(reference.target_name)


def _relation_type(
    relation: str,
    source: ComponentNode | None,
    target: ComponentNode,
) -> str | None:
    if relation != BASE_RELATION:
        return relation

    # A class implements an interface; an interface extends an interface.
    if target.kind == NodeKind.INTERFACE and (source is None or source.kind != NodeKind.INTERFACE):
        return RelationType.IMPLEMENTS
    return RelationType.INHERITS


def merge_relations(relations: Iterable[ComponentRelation]) -> list[ComponentRelation]:
    """Keep one edge per (source, target), preferring the strongest relationship."""
    best: dict[tuple[str, str], tuple[int, ComponentRelation]] = {}

    for relation in relations:
        priority = _RELATION_PRIORITY.get(str(relation.type), 3)
        key = (relation.source_id, relation.target_id)
        current = best.get(key)
        if current is None or priority < current[0]:
            best[key] = (priority, relation)

    return sorted(
        (relation for _, relation in best.values()),
        key=lambda r: (r.source_id, str(r.type), r.target_id),
    )


def drop_dangling_relations(
    relations: Iterable[ComponentRelation],
    nodes: list[ComponentNode],
) -> list[ComponentRelation]:
    ids = {node.id for node in nodes}
    return [r for r in relations if r.source_id in ids and r.target_id in ids]
