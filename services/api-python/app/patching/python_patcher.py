"""Surgical Python edits with Tree-sitter byte offsets (Phase 12).

Only the targeted class attribute/annotation spans are rewritten; methods, docstrings, comments and
formatting elsewhere in the file keep their exact bytes. Nothing is written to disk — the caller gets
proposed text through the Phase 3b dry-run and the Phase 3c guarded apply.
"""

from __future__ import annotations

import functools
import re

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from app.patching.models import PatchField, PatchOperation, PatchOutcome
from app.patching.tree_utils import (
    line_ending,
    line_indent,
    line_removal_end,
    line_start,
    node_text,
    splice,
    walk,
)

_FIELD_CALLS = frozenset({"Field", "Column", "mapped_column", "relationship"})

_IMPORT_MAP = {
    "Field": "from pydantic import Field",
    "BaseModel": "from pydantic import BaseModel",
    "dataclass": "from dataclasses import dataclass",
    "Mapped": "from sqlalchemy.orm import Mapped",
    "mapped_column": "from sqlalchemy.orm import mapped_column",
    "relationship": "from sqlalchemy.orm import relationship",
    "Column": "from sqlalchemy import Column",
    "ForeignKey": "from sqlalchemy import ForeignKey",
    "Decimal": "from decimal import Decimal",
    "UUID": "from uuid import UUID",
    "datetime": "from datetime import datetime",
    "date": "from datetime import date",
}

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IMPORT_LINE_RE = re.compile(
    r"^(?:from\s+[\w.]+\s+import\s+.+|import\s+.+)$", re.MULTILINE
)


class _Skip(ValueError):
    """The operation cannot be applied safely; report a warning and keep the file byte-identical."""


@functools.lru_cache(maxsize=1)
def _parser() -> Parser:
    return Parser(Language(tree_sitter_python.language()))


def patch_python(content: str, operations: list[PatchOperation]) -> PatchOutcome:
    source = content.encode("utf-8")
    applied: list[str] = []
    warnings: list[str] = []
    imports: set[str] = set()

    for operation in operations:
        type_name = _simple_name(operation.type_name)
        if not type_name:
            warnings.append(f"{operation.op}: typeName is required; operation skipped.")
            continue

        root = _parser().parse(source).root_node
        declaration = _find_class(root, type_name, source)
        if declaration is None:
            warnings.append(
                f"{operation.op}: no class named '{type_name}' in this file. Module-level Python routers "
                "have no editable fields; edit the route module by hand."
            )
            continue

        try:
            source, note = _apply(source, declaration, operation)
        except _Skip as exc:
            warnings.append(f"{operation.op} {type_name}: {exc}")
            continue

        applied.append(_describe(operation, type_name))
        if note:
            warnings.append(note)
        imports |= _import_names_for(operation)

    source, import_warnings = _ensure_imports(source, imports)
    warnings.extend(import_warnings)
    return PatchOutcome(source.decode("utf-8", errors="replace"), applied, warnings)


def _apply(source: bytes, declaration: Node, operation: PatchOperation) -> tuple[bytes, str | None]:
    if operation.op in {"add_field", "add_dependency"}:
        return _add_field(source, declaration, operation, dependency=operation.op == "add_dependency")
    if operation.op == "update_field":
        return _update_field(source, declaration, operation)
    if operation.op in {"remove_field", "remove_dependency"}:
        return _remove_field(source, declaration, operation)
    if operation.op == "add_annotation":
        return _add_annotation(source, declaration, operation)
    if operation.op == "remove_annotation":
        return _remove_annotation(source, declaration, operation)
    raise _Skip(f"unsupported operation '{operation.op}'.")


def _add_field(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
    *,
    dependency: bool,
) -> tuple[bytes, str | None]:
    field = operation.field
    if field is None or not field.name.strip():
        raise _Skip("field details are required.")

    body = declaration.child_by_field_name("body")
    if body is None:
        raise _Skip("the class has no body.")

    name = field.name.strip()
    if _find_field(declaration, name, source) is not None:
        raise _Skip(f"attribute '{name}' already exists.")

    indent = _member_indent(source, body)
    eol = line_ending(source)
    line = _render_field_line(field)

    members = _field_members(body, source)
    if members:
        insert_at = line_removal_end(source, members[-1].end_byte)
        insertion = f"{indent}{line}{eol}"
    else:
        insert_at = _first_body_insertion(source, body)
        insertion = f"{indent}{line}{eol}"

    note = None
    if dependency:
        note = (
            f"Added attribute '{name}': Python has no field injection, so wire it in "
            "__init__ or through a FastAPI Depends(...) provider."
        )
    return splice(source, [(insert_at, insert_at, insertion.encode("utf-8"))]), note


def _update_field(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, str | None]:
    field = operation.field
    if field is None or not field.name.strip():
        raise _Skip("field details are required.")

    found = _find_field(
        declaration, operation.original_name or operation.field_name or field.name, source
    )
    if found is None:
        raise _Skip(f"attribute '{operation.original_name or operation.field_name or field.name}' was not found.")

    _statement, assignment, left = found
    old_name = node_text(source, left).strip()
    if not old_name:
        raise _Skip("the target attribute has no resolvable name.")

    edits: list[tuple[int, int, bytes]] = []
    type_node = assignment.child_by_field_name("type")
    new_type = field.type.strip()
    if type_node is not None and new_type and node_text(source, type_node).strip() != new_type:
        edits.append((type_node.start_byte, type_node.end_byte, new_type.encode("utf-8")))
    elif type_node is None and new_type:
        edits.append((left.end_byte, left.end_byte, f": {new_type}".encode()))

    new_name = field.name.strip()
    note = None
    if old_name != new_name:
        edits.append((left.start_byte, left.end_byte, new_name.encode("utf-8")))
        renamed = _reference_rename_edits(source, declaration, old_name, new_name, left)
        edits.extend(renamed)
        if renamed:
            note = (
                f"Renamed {len(renamed)} reference(s) from '{old_name}' to '{new_name}'; "
                "review those lines in the diff."
            )

    if field.annotations:
        note = _merge_note(note, "Attribute annotations are RHS calls in Python; edit them by hand if needed.")

    return splice(source, edits), note


def _remove_field(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    name = operation.field_name or (operation.field.name if operation.field else None)
    if not name:
        raise _Skip("fieldName is required.")

    found = _find_field(declaration, name, source)
    if found is None:
        raise _Skip(f"attribute '{name}' was not found.")

    statement, _assignment, _left = found
    start = line_start(source, statement.start_byte)
    if source[start : statement.start_byte].strip(b" \t") != b"":
        start = statement.start_byte
    end = line_removal_end(source, statement.end_byte)
    return splice(source, [(start, end, b"")]), None


def _add_annotation(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    annotation = _normalize_annotation(operation.annotation)
    if not annotation:
        raise _Skip("annotation is required.")

    if operation.field_name:
        return (
            _add_field_annotation(source, declaration, operation.field_name, _last_segment(annotation)),
            None,
        )

    decorator_text = f"@{annotation}"
    if any(_decorator_name(node, source) == annotation for node in _decorators(declaration)):
        raise _Skip(f"annotation @{annotation} is already present.")

    target = declaration.parent if declaration.parent is not None and declaration.parent.type == "decorated_definition" else declaration
    indent = line_indent(source, target.start_byte)
    indent = indent if indent is not None else ""
    insertion = f"{indent}{decorator_text}{line_ending(source)}"
    return splice(source, [(target.start_byte, target.start_byte, insertion.encode("utf-8"))]), None


def _add_field_annotation(
    source: bytes,
    declaration: Node,
    field_name: str,
    annotation: str,
) -> bytes:
    if annotation not in _FIELD_CALLS:
        raise _Skip(
            f"@{annotation} is not a supported Python attribute call "
            f"({', '.join(sorted(_FIELD_CALLS))})."
        )
    found = _find_field(declaration, field_name, source)
    if found is None:
        raise _Skip(f"attribute '{field_name}' was not found.")
    _statement, assignment, _left = found
    right = assignment.child_by_field_name("right")
    if right is not None:
        raise _Skip(f"attribute '{field_name}' already has a value; cannot attach @{annotation} safely.")

    suffix = "..." if annotation == "Field" else ""
    insertion = f" = {annotation}({suffix})"
    return splice(source, [(assignment.end_byte, assignment.end_byte, insertion.encode("utf-8"))])


def _remove_annotation(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    annotation = _normalize_annotation(operation.annotation)
    if not annotation:
        raise _Skip("annotation is required.")

    if operation.field_name:
        found = _find_field(declaration, operation.field_name, source)
        if found is None:
            raise _Skip(f"attribute '{operation.field_name}' was not found.")
        _statement, assignment, left = found
        right = assignment.child_by_field_name("right")
        if right is None or right.type != "call":
            raise _Skip(f"attribute '{operation.field_name}' has no annotation call to remove.")
        if node_text(source, right.child_by_field_name("function")).strip().split(".")[-1] != annotation:
            raise _Skip(f"attribute '{operation.field_name}' is not annotated with @{annotation}.")
        equals = source.rfind(b"=", left.end_byte, right.start_byte)
        start = equals if equals >= 0 else right.start_byte
        while start > left.end_byte and source[start - 1 : start] in {b" ", b"\t"}:
            start -= 1
        return splice(source, [(start, right.end_byte, b"")]), None

    match = next(
        (node for node in _decorators(declaration) if _decorator_name(node, source) == annotation),
        None,
    )
    if match is None:
        raise _Skip(f"annotation @{annotation} was not found.")

    start = line_start(source, match.start_byte)
    end = line_removal_end(source, match.end_byte)
    return splice(source, [(start, end, b"")]), None


# ------------------------------------------------------------------------------- helpers


def _render_field_line(field: PatchField) -> str:
    name = field.name.strip()
    type_text = field.type.strip() or "object"
    markers = [
        _last_segment(item)
        for item in field.annotations
        if _last_segment(item) in _FIELD_CALLS
    ]
    line = f"{name}: {type_text}"
    if markers:
        marker = markers[0]
        suffix = "..." if marker == "Field" else ""
        line = f"{line} = {marker}({suffix})"
    return line


def _reference_rename_edits(
    source: bytes,
    declaration: Node,
    old_name: str,
    new_name: str,
    declaration_name: Node,
) -> list[tuple[int, int, bytes]]:
    edits: list[tuple[int, int, bytes]] = []
    replacement = new_name.encode("utf-8")

    for node in walk(declaration):
        if node.type != "identifier" or node_text(source, node) != old_name:
            continue
        if node.start_byte == declaration_name.start_byte:
            continue
        edits.append((node.start_byte, node.end_byte, replacement))
    return edits


def _member_indent(source: bytes, body: Node) -> str:
    for child in body.children:
        indent = line_indent(source, child.start_byte)
        if indent is not None:
            return indent
    return "    "


def _first_body_insertion(source: bytes, body: Node) -> int:
    """Insert after the docstring (when present) so class documentation stays first."""
    children = [child for child in body.children if child.type != "comment"]
    if children and children[0].type == "expression_statement":
        first = children[0]
        if first.children and first.children[0].type == "string":
            return line_removal_end(source, first.end_byte)
    return line_start(source, body.start_byte)


def _field_members(body: Node, source: bytes) -> list[Node]:
    members: list[Node] = []
    for child in body.children:
        if child.type != "expression_statement" or not child.children:
            continue
        assignment = child.children[0]
        if assignment.type != "assignment":
            continue
        left = assignment.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            members.append(child)
    return members


def _find_class(root: Node, name: str, source: bytes) -> Node | None:
    for node in walk(root):
        if node.type != "class_definition":
            continue
        if node_text(source, node.child_by_field_name("name")).strip() == name:
            return node
    return None


def _find_field(declaration: Node, name: str, source: bytes) -> tuple[Node, Node, Node] | None:
    body = declaration.child_by_field_name("body")
    if body is None:
        return None
    for child in body.children:
        if child.type != "expression_statement" or not child.children:
            continue
        assignment = child.children[0]
        if assignment.type != "assignment":
            continue
        left = assignment.child_by_field_name("left")
        if left is not None and left.type == "identifier" and node_text(source, left).strip() == name:
            return child, assignment, left
    return None


def _decorators(declaration: Node) -> list[Node]:
    parent = declaration.parent
    if parent is None or parent.type != "decorated_definition":
        return []
    return [child for child in parent.children if child.type == "decorator"]


def _decorator_name(node: Node, source: bytes) -> str:
    return _normalize_annotation(node_text(source, node))


def _strip_decorator(raw: str) -> str:
    text = raw.strip().lstrip("@").strip()
    return text.split("(", 1)[0].strip()


def _normalize_annotation(value: str | None) -> str:
    return _strip_decorator(value or "")


def _last_segment(value: str | None) -> str:
    normalized = _normalize_annotation(value)
    return normalized.split(".")[-1] if normalized else ""


def _import_names_for(operation: PatchOperation) -> set[str]:
    names: set[str] = set()
    field = operation.field
    if field is not None:
        names.update(_IDENTIFIER_RE.findall(field.type))
        names.update(_last_segment(item) for item in field.annotations)
    names.add(_last_segment(operation.annotation))
    return {name for name in names if name in _IMPORT_MAP}


def _ensure_imports(source: bytes, names: set[str]) -> tuple[bytes, list[str]]:
    if not names:
        return source, []

    existing = _imported_names(source)
    missing = sorted(
        {statement for name, statement in _IMPORT_MAP.items() if name in names and name not in existing}
    )
    if not missing:
        return source, []

    eol = line_ending(source)
    text = source.decode("utf-8", errors="replace")
    offset = _import_insertion_offset(text)
    block = "".join(f"{eol}{statement}" for statement in missing)
    updated = text[:offset] + block + text[offset:]
    return updated.encode("utf-8"), []


def _imported_names(source: bytes) -> set[str]:
    text = source.decode("utf-8", errors="replace")
    names: set[str] = set()
    for line in _IMPORT_LINE_RE.findall(text):
        if line.strip().startswith("import "):
            names.update(part.strip().split(" as ")[0].split(".")[0] for part in line.split(None, 1)[1].split(","))
            continue
        _, _, imported = line.partition(" import ")
        for part in imported.split(","):
            names.add(part.strip().split(" as ")[0].strip())
    return {name for name in names if name}


def _import_insertion_offset(text: str) -> int:
    matches = list(_IMPORT_LINE_RE.finditer(text))
    if matches:
        return matches[-1].end()
    stripped = text.lstrip()
    if stripped.startswith(('"""', "'''")):
        quote = stripped[:3]
        end = text.find(quote, text.find(quote) + 3)
        if end != -1:
            newline = text.find("\n", end)
            return len(text) if newline == -1 else newline
    return 0


def _describe(operation: PatchOperation, type_name: str) -> str:
    label = {
        "add_field": "add field",
        "update_field": "update field",
        "remove_field": "remove field",
        "add_annotation": "add annotation",
        "remove_annotation": "remove annotation",
        "add_dependency": "add dependency",
        "remove_dependency": "remove dependency",
    }[operation.op]
    field = operation.field.name if operation.field is not None else operation.field_name or ""
    return f"{label}: {type_name}.{field}".rstrip(".") if field else f"{label}: {type_name}"


def _merge_note(note: str | None, extra: str) -> str:
    return f"{note} {extra}" if note else extra


def _simple_name(value: str | None) -> str:
    return (value or "").strip().split(".")[-1]


__all__ = ["patch_python"]
