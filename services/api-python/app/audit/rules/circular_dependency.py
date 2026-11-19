"""CIRCULAR_DEPENDENCY — strongly connected components in the dependency graph."""

from __future__ import annotations

from collections import deque
from itertools import pairwise

from app.audit.context import DEPENDENCY_RELATIONS, AuditContext
from app.audit.engine import audit_rule
from app.models.ir import (
    AuditFinding,
    AuditRuleId,
    ComponentNode,
    ComponentRelation,
    Severity,
)


def _adjacency(context: AuditContext) -> dict[str, list[str]]:
    graph: dict[str, set[str]] = {node.id: set() for node in context.nodes}
    for relation in context.relations:
        if relation.type not in DEPENDENCY_RELATIONS:
            continue
        if relation.source_id in graph and relation.target_id in graph:
            graph[relation.source_id].add(relation.target_id)
    return {node_id: sorted(targets) for node_id, targets in graph.items()}


def _strongly_connected(graph: dict[str, list[str]]) -> list[list[str]]:
    """Iterative Tarjan — deep dependency chains must not hit the recursion limit."""
    index = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    for root in sorted(graph):
        if root in indices:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, position = work[-1]
            if position == 0:
                indices[node] = index
                low[node] = index
                index += 1
                stack.append(node)
                on_stack.add(node)

            if position < len(graph[node]):
                neighbour = graph[node][position]
                work[-1] = (node, position + 1)
                if neighbour not in indices:
                    work.append((neighbour, 0))
                elif neighbour in on_stack:
                    low[node] = min(low[node], indices[neighbour])
                continue

            work.pop()
            if low[node] == indices[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

    return components


def _shortest_cycle(members: set[str], graph: dict[str, list[str]]) -> list[str]:
    """Deterministic shortest cycle from the lexicographically smallest member."""
    start = min(members)
    queue: deque[list[str]] = deque([[start]])
    visited = {start}

    while queue:
        path = queue.popleft()
        for neighbour in graph[path[-1]]:
            if neighbour == start and len(path) > 1:
                return [*path, start]
            if neighbour in members and neighbour not in visited:
                visited.add(neighbour)
                queue.append(path + [neighbour])

    ordered = sorted(members)
    return [*ordered, ordered[0]]


def _edge_keys(path: list[str], relations: tuple[ComponentRelation, ...]) -> list[str]:
    keys: list[str] = []
    for source, target in pairwise(path):
        candidates = [
            relation
            for relation in relations
            if relation.source_id == source
            and relation.target_id == target
            and relation.type in DEPENDENCY_RELATIONS
        ]
        if not candidates:
            continue
        strongest = min(candidates, key=lambda relation: (relation.type,))
        keys.append(f"{strongest.source_id}->{strongest.target_id}")
    return sorted(set(keys))


@audit_rule
def circular_dependency(context: AuditContext) -> list[AuditFinding]:
    graph = _adjacency(context)
    findings: list[AuditFinding] = []

    for component in _strongly_connected(graph):
        if len(component) < 2:
            continue

        members = set(component)
        cycle = _shortest_cycle(members, graph)
        names = [context.by_id[node_id].name for node_id in cycle]
        first: ComponentNode = context.by_id[component[0]]

        findings.append(
            AuditFinding(
                id=f"{AuditRuleId.CIRCULAR_DEPENDENCY}:{','.join(component)}",
                rule_id=AuditRuleId.CIRCULAR_DEPENDENCY,
                severity=Severity.ERROR,
                title=f"Circular dependency across {len(component)} components",
                message=(
                    f"`{'` → `'.join(names)}` form a dependency cycle, so none of them can be built, "
                    f"tested or deployed in isolation."
                ),
                suggestion=(
                    "Break the cycle by extracting the shared behaviour into a third component, "
                    "inverting one edge with an interface, or moving the shared types into a lower layer."
                ),
                node_ids=list(component),
                edge_keys=_edge_keys(cycle, context.relations),
                file_path=first.file_path,
            )
        )

    return findings
