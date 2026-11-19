"""Rule package — import side effects register every rule with the engine."""

from app.audit.rules import (
    circular_dependency,
    entity_exposed,
    god_class,
    layer_violation,
    missing_validation,
    orphan_component,
)

__all__ = [
    "circular_dependency",
    "entity_exposed",
    "god_class",
    "layer_violation",
    "missing_validation",
    "orphan_component",
]
