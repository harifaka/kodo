"""Surgical TypeScript/JavaScript edits with Tree-sitter byte offsets.

Class properties and interface fields are inserted, rewritten or removed in place; methods,
comments and formatting elsewhere keep their exact bytes. The file is never written to disk.
"""

from __future__ import annotations

import functools

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from app.patching.models import PatchField, PatchOperation, PatchOutcome
from app.patching.tree_utils import (
    detect_member_indent,
    detect_type_indent,
    line_end,
    line_ending,
    line_indent,
    line_removal_end,
    line_start,
    node_text,
    splice,
    walk,
)

_TS_TYPES = frozenset({"class_declaration", "abstract_class_declaration", "interface_declaration"})
_CLASS_FIELD_TYPES = frozenset({"public_field_definition", "field_definition", "property_declaration"})
_INTERFACE_FIELD_TYPES = frozenset({"property_signature"})
_NAME_PARENTS = frozenset(
    {
        "method_definition",
        "method_signature",
        "public_field_definition",
        "field_definition",
        "property_declaration",
        "property_signature",
        "class_declaration",
        "abstract_class_declaration",
        "interface_declaration",
        "variable_declarator",
    }
)


class _Skip(ValueError):
    """The operation cannot be applied safely; keep the file byte-identical."""


@functools.lru_cache(maxsize=4)
def _language(kind: str) -> Language:
    return Language(
        {
            "ts": tree_sitter_typescript.language_typescript,
            "tsx": tree_sitter_typescript.language_tsx,
            "js": tree_sitter_javascript.language,
        }[kind]()
    )


@functools.lru_cache(maxsize=4)
def _parser(kind: str) -> Parser:
    return Parser(_language(kind))


def _language_kind(file_path: str) -> str:
    lowered = file_path.lower()
    if lowered.endswith(".tsx"):
        return "tsx"
    if lowered.endswith((".ts", ".mts", ".cts")):
        return "ts"
    return "js"


def patch_script(content: str, operations: list[PatchOperation], file_path: str) -> PatchOutcome:
    source = content.encode("utf-8")
    applied: list[str] = []
    warnings: list[str] = []
    parser = _parser(_language_kind(file_path))

    for operation in operations:
        type_name = _simple_name(operation.type_name)
        if not type_name:
            warnings.append(f"{operation.op}: typeName is required; operation skipped.")
            continue

        root = parser.parse(source).root_node
        declaration = _find_type(root, type_name, source)
        if declaration is None:
            warnings.append(
                f"{operation.op}: type '{type_name}' was not found in this file; operation skipped."
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
        raise _Skip("the target type has no body.")

    if _find_field(declaration, field.name, source) is not None:
        raise _Skip(f"field '{field.name}' already exists.")

    interface = declaration.type == "interface_declaration"
    base_indent = detect_type_indent(source, declaration)
    indent = detect_member_indent(source, body, base_indent).text
    warnings: list[str] = []
    lines = _render_member(field, indent, interface, warnings)
    if warnings:
        raise _Skip(warnings[0])

    eol = line_ending(source)
    members = _field_members(body, interface)
    if members:
        insert_at = line_end(source, members[-1].end_byte)
    else:
        insert_at = body.start_byte + 1

    note = None
    if dependency:
        note = (
            f"Added dependency property '{field.name}' to '{_node_name(declaration, source)}'; "
            "constructor wiring must be done by hand."
        )
    return splice(source, [(insert_at, insert_at, (eol + eol.join(lines)).encode("utf-8"))]), note


def _update_field(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, str | None]:
    field = operation.field
    if field is None or not field.name.strip():
        raise _Skip("field details are required.")

    original = operation.original_name or operation.field_name or field.name
    member = _find_field(declaration, original, source)
    if member is None:
        raise _Skip(f"field '{original}' was not found.")

    interface = declaration.type == "interface_declaration"
    if interface and field.annotations:
        raise _Skip("TypeScript interfaces cannot carry decorators; remove the annotations.")

    old_name = node_text(source, member.child_by_field_name("name")).strip()
    value = member.child_by_field_name("value")
    initializer = node_text(source, value).strip() if value is not None else ""

    warnings: list[str] = []
    lines = _render_member(field, _indent_for(source, member), interface, warnings, initializer)
    eol = line_ending(source)
    text = eol.join(lines)

    start = line_start(source, member.start_byte)
    if source[start:member.start_byte].strip(b" \t") != b"":
        start = member.start_byte
    edits: list[tuple[int, int, bytes]] = [(start, _member_end(source, member), text.encode("utf-8"))]

    note = None
    if old_name and old_name != field.name.strip():
        renamed = _reference_rename_edits(source, declaration, old_name, field.name.strip(), member)
        edits.extend(renamed)
        if renamed:
            note = (
                f"Renamed {len(renamed)} reference(s) from '{old_name}' to '{field.name.strip()}'; "
                "review those lines in the diff."
            )

    return splice(source, edits), note


def _remove_field(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    field_name = operation.field_name or (operation.field.name if operation.field else None)
    if not field_name:
        raise _Skip("fieldName is required.")

    member = _find_field(declaration, field_name, source)
    if member is None:
        raise _Skip(f"field '{field_name}' was not found.")

    start = line_start(source, member.start_byte)
    if source[start:member.start_byte].strip(b" \t") != b"":
        start = member.start_byte
    return splice(source, [(start, line_removal_end(source, _member_end(source, member)), b"")]), None


def _add_annotation(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    decorator = _normalize_decorator(operation.annotation)
    if not decorator:
        raise _Skip("annotation is required.")
    if declaration.type == "interface_declaration":
        raise _Skip("TypeScript interfaces cannot carry decorators.")

    if any(_decorator_name(node, source) == _decorator_name_text(decorator) for node in _decorators(declaration)):
        raise _Skip(f"annotation {decorator} is already present.")

    anchor = declaration.parent if _is_export(declaration) else declaration
    if anchor is None:
        anchor = declaration
    indent = detect_type_indent(source, anchor)
    insertion = f"{decorator}{line_ending(source)}{indent}".encode()
    return splice(source, [(anchor.start_byte, anchor.start_byte, insertion)]), None


def _remove_annotation(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    name = _decorator_name_text(operation.annotation)
    if not name:
        raise _Skip("annotation is required.")

    match = next((node for node in _decorators(declaration) if _decorator_name(node, source) == name), None)
    if match is None:
        raise _Skip(f"annotation {operation.annotation} was not found.")

    start = line_start(source, match.start_byte)
    prefix = source[start:match.start_byte]
    end_of_line = line_end(source, match.end_byte)
    suffix = source[match.end_byte:end_of_line]
    if prefix.strip(b" \t") == b"" and suffix.strip(b" \t") == b"":
        return splice(source, [(start, line_removal_end(source, match.end_byte), b"")]), None
    return splice(source, [(match.start_byte, match.end_byte, b"")]), None


def _render_member(
    field: PatchField,
    indent: str,
    interface: bool,
    warnings: list[str],
    initializer: str = "",
) -> list[str]:
    type_text = field.type.strip() or ("unknown" if interface else "any")
    value = f" = {initializer}" if initializer else ""

    if interface:
        if field.annotations:
            warnings.append("TypeScript interfaces cannot carry decorators.")
        return [f"{indent}{field.name.strip()}: {type_text}{value};"]

    decorators = [_normalize_decorator(item) for item in field.annotations]
    lines = [f"{indent}{decorator}" for decorator in decorators if decorator]
    visibility = _ts_visibility(field.visibility)
    modifiers = f"{visibility} " if visibility else ""
    lines.append(f"{indent}{modifiers}{field.name.strip()}: {type_text}{value};")
    return lines


def _reference_rename_edits(
    source: bytes,
    declaration: Node,
    old_name: str,
    new_name: str,
    target_member: Node,
) -> list[tuple[int, int, bytes]]:
    edits: list[tuple[int, int, bytes]] = []
    replacement = new_name.encode("utf-8")

    for node in walk(declaration):
        if node.type not in {"identifier", "property_identifier"}:
            continue
        if node_text(source, node) != old_name:
            continue
        if node.start_byte >= target_member.start_byte and node.end_byte <= target_member.end_byte:
            continue

        parent = node.parent
        if parent is not None:
            declaration_name = parent.child_by_field_name("name")
            if (
                parent.type in _NAME_PARENTS
                and declaration_name is not None
                and declaration_name.start_byte == node.start_byte
            ):
                continue
        if _inside_decorator(node):
            continue
        edits.append((node.start_byte, node.end_byte, replacement))

    return edits


def _inside_decorator(node: Node) -> bool:
    current = node.parent
    while current is not None:
        if current.type == "decorator":
            return True
        if current.type in _TS_TYPES:
            return False
        current = current.parent
    return False


def _decorators(declaration: Node) -> list[Node]:
    nodes = [child for child in declaration.children if child.type == "decorator"]
    parent = declaration.parent
    if parent is not None and parent.type == "export_statement":
        nodes.extend(child for child in parent.children if child.type == "decorator")
    return nodes


def _is_export(declaration: Node) -> bool:
    return declaration.parent is not None and declaration.parent.type == "export_statement"


def _decorator_name(node: Node, source: bytes) -> str:
    return _decorator_name_text(node_text(source, node))


def _decorator_name_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.split("(", 1)[0].strip().lstrip("@").strip()
    return text.split(".")[-1].strip()


def _normalize_decorator(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("["):
        text = text.strip("[]").strip()
    if not text.startswith("@"):
        text = f"@{text.lstrip('@')}"
    return text


def _ts_visibility(value: str | None) -> str:
    words = [word for word in (value or "").split() if word in {"public", "private", "protected", "readonly"}]
    return " ".join(words)


def _find_type(root: Node, type_name: str, source: bytes) -> Node | None:
    for node in walk(root):
        if node.type in _TS_TYPES and _node_name(node, source) == type_name:
            return node
    return None


def _node_name(node: Node, source: bytes) -> str:
    return node_text(source, node.child_by_field_name("name")).strip()


def _field_members(body: Node, interface: bool) -> list[Node]:
    allowed = _INTERFACE_FIELD_TYPES if interface else _CLASS_FIELD_TYPES
    return [child for child in body.children if child.type in allowed]


def _find_field(declaration: Node, name: str, source: bytes) -> Node | None:
    body = declaration.child_by_field_name("body")
    if body is None:
        return None
    for member in body.children:
        if member.type not in _CLASS_FIELD_TYPES | _INTERFACE_FIELD_TYPES:
            continue
        if node_text(source, member.child_by_field_name("name")).strip() == name:
            return member
    return None


def _member_end(source: bytes, member: Node) -> int:
    """`public_field_definition` excludes its trailing `;`/`,` sibling token."""
    end = member.end_byte
    while end < len(source) and source[end : end + 1] in {b" ", b"\t"}:
        end += 1
    if end < len(source) and source[end : end + 1] in {b";", b","}:
        end += 1
    return end


def _indent_for(source: bytes, node: Node) -> str:
    indent = line_indent(source, node.start_byte)
    if indent is not None:
        return indent
    parent = node.parent
    if parent is None:
        return "    "
    base = detect_type_indent(source, parent)
    return detect_member_indent(source, parent, base).text


def _describe(operation: PatchOperation, type_name: str) -> str:
    if operation.field is not None:
        detail = f"{type_name}.{operation.field.name}"
    elif operation.field_name:
        detail = f"{type_name}.{operation.field_name}"
    elif operation.annotation:
        detail = f"{type_name} {operation.annotation}"
    else:
        detail = type_name
    return f"{operation.op} {detail}"


def _simple_name(value: str | None) -> str:
    return (value or "").strip().split(".")[-1]
