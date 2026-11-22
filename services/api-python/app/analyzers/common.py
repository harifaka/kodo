"""Shared helpers for the tree-sitter analyzers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from app.models.ir import ComponentNode

# Marker used while parsing; resolved to `inherits` vs `implements` once all node kinds are known.
BASE_RELATION = "__base"

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WHITESPACE_RE = re.compile(r"\s+")

# Primitives and language keywords never resolve to a discovered component.
_NON_TYPE_IDENTIFIERS = frozenset(
    {
        "void", "var", "let", "const", "int", "long", "short", "byte", "float", "double",
        "decimal", "boolean", "bool", "char", "string", "str", "object", "any", "unknown",
        "never", "number", "bigint", "symbol", "true", "false", "null", "undefined", "this",
        "super", "new", "return", "async", "await", "static", "public", "private", "protected",
        "readonly", "final", "extends", "implements", "interface", "class", "record", "enum",
        "module", "namespace", "import", "export", "default", "from", "of", "in", "as", "is",
        "keys", "values", "entries", "map", "filter", "reduce", "Integer", "Long",
        "Boolean", "Double", "Float", "Object", "Void", "Character",
    }
)


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    """An unresolved edge discovered while walking a syntax tree."""

    source_id: str
    target_name: str
    relation: str
    file_hint: str | None = None


@dataclass
class ParseResult:
    nodes: list[ComponentNode] = field(default_factory=list)
    references: list[ReferenceCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def type_identifiers(type_text: str) -> list[str]:
    """Extract candidate component names from a type expression (`Map<String, Order>` -> String, Map, Order)."""
    seen: set[str] = set()
    names: list[str] = []
    for match in _IDENTIFIER_RE.finditer(type_text):
        value = match.group(0)
        if value in _NON_TYPE_IDENTIFIERS or value in seen:
            continue
        seen.add(value)
        names.append(value)
    return names


def last_identifier(type_text: str) -> str:
    """`com.acme.orders.Order` -> `Order`, `List<Order>` -> `Order` is not desired, so callers pass base names."""
    matches = _IDENTIFIER_RE.findall(type_text)
    return matches[-1] if matches else ""


def base_type_name(type_text: str) -> str:
    """`AbstractService<Order>` -> `AbstractService`, `com.acme.Base` -> `Base`."""
    head = type_text.split("<", 1)[0]
    return last_identifier(head)


def normalize_type(type_text: str) -> str:
    return _WHITESPACE_RE.sub(" ", type_text).strip().lstrip(":").strip()


def strip_generics(type_text: str) -> str:
    """`List<Order>` -> `List` (Mermaid member rendering only)."""
    return type_text.split("<", 1)[0].strip()


def render_parameter(type_text: str, name: str) -> str:
    type_text = normalize_type(type_text)
    return f"{type_text} {name}".strip()


def normalize_annotation(raw: str, *, style: Literal["at", "bracket"]) -> str:
    """`@RestController("x")` -> `@RestController`; `[ApiController]` -> `[ApiController]`."""
    text = raw.strip()
    if "(" in text:
        text = text.split("(", 1)[0]
    text = text.lstrip("@[").removesuffix("]").strip()
    name = text.split(".")[-1].strip()
    if not name:
        return ""
    return f"@{name}" if style == "at" else f"[{name}]"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def posix_rel(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()
