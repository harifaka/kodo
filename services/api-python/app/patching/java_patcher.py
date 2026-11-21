"""Surgical Java edits with Tree-sitter byte offsets.

Only the targeted field/annotation spans are rewritten; methods, comments and formatting elsewhere
in the file keep their exact bytes. Nothing is written to disk — the caller gets proposed text only.
"""

from __future__ import annotations

import functools
import re

import tree_sitter_java
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

_JAVA_TYPES = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
    }
)
_ANNOTATION_TYPES = frozenset({"annotation", "marker_annotation"})
_DECLARATION_NAME_PARENTS = frozenset(
    {
        "method_declaration",
        "constructor_declaration",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "annotation_type_declaration",
        "variable_declarator",
        "formal_parameter",
    }
)

_IMPORT_MAP = {
    # Bean Validation
    "NotNull": "jakarta.validation.constraints.NotNull",
    "NotBlank": "jakarta.validation.constraints.NotBlank",
    "NotEmpty": "jakarta.validation.constraints.NotEmpty",
    "Size": "jakarta.validation.constraints.Size",
    "Min": "jakarta.validation.constraints.Min",
    "Max": "jakarta.validation.constraints.Max",
    "Pattern": "jakarta.validation.constraints.Pattern",
    "Email": "jakarta.validation.constraints.Email",
    "Positive": "jakarta.validation.constraints.Positive",
    "PositiveOrZero": "jakarta.validation.constraints.PositiveOrZero",
    "Past": "jakarta.validation.constraints.Past",
    "Future": "jakarta.validation.constraints.Future",
    "Valid": "jakarta.validation.Valid",
    # JPA
    "Column": "jakarta.persistence.Column",
    "Entity": "jakarta.persistence.Entity",
    "Table": "jakarta.persistence.Table",
    "Id": "jakarta.persistence.Id",
    "GeneratedValue": "jakarta.persistence.GeneratedValue",
    "ManyToOne": "jakarta.persistence.ManyToOne",
    "OneToMany": "jakarta.persistence.OneToMany",
    "OneToOne": "jakarta.persistence.OneToOne",
    "ManyToMany": "jakarta.persistence.ManyToMany",
    "JoinColumn": "jakarta.persistence.JoinColumn",
    # Common types
    "BigDecimal": "java.math.BigDecimal",
    "UUID": "java.util.UUID",
    "LocalDateTime": "java.time.LocalDateTime",
    "LocalDate": "java.time.LocalDate",
    "LocalTime": "java.time.LocalTime",
    "List": "java.util.List",
    "Set": "java.util.Set",
    "Map": "java.util.Map",
    "Optional": "java.util.Optional",
    "JsonProperty": "com.fasterxml.jackson.annotation.JsonProperty",
}

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)
_PACKAGE_RE = re.compile(r"^\s*package\s+[\w.]+\s*;", re.MULTILINE)


class _Skip(ValueError):
    """The operation cannot be applied safely; report a warning and keep the file byte-identical."""


@functools.lru_cache(maxsize=1)
def _parser() -> Parser:
    return Parser(Language(tree_sitter_java.language()))


def patch_java(content: str, operations: list[PatchOperation]) -> PatchOutcome:
    source = content.encode("utf-8")
    applied: list[str] = []
    warnings: list[str] = []
    import_names: set[str] = set()

    for operation in operations:
        type_name = _simple_name(operation.type_name)
        if not type_name:
            warnings.append(f"{operation.op}: typeName is required; operation skipped.")
            continue

        root = _parser().parse(source).root_node
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
        import_names |= _import_names_for(operation)

    source, import_warnings = _ensure_imports(source, import_names)
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

    if declaration.type in {"interface_declaration", "enum_declaration"}:
        raise _Skip("fields cannot be added to a Java interface/enum without an initializer.")

    body = declaration.child_by_field_name("body")
    if body is None:
        raise _Skip("the target type has no body; add a body before inserting fields.")

    if _find_field(declaration, field.name, source) is not None:
        raise _Skip(f"field '{field.name}' already exists.")

    base_indent = detect_type_indent(source, declaration)
    indent = detect_member_indent(source, body, base_indent).text
    lines = _render_field_lines(field, indent, dependency=dependency)
    eol = line_ending(source)

    fields = _field_members(body)
    if fields:
        # Insert after the full line terminator: landing on the "\n" of a CRLF line would
        # duplicate the "\r" and mix line endings once the patch is written to disk.
        insert_at = line_removal_end(source, fields[-1].end_byte)
        insertion = eol + eol.join(lines) + eol
    else:
        insert_at = body.start_byte + 1
        insertion = eol + eol.join(lines)
    note = None
    if dependency:
        note = (
            f"Added dependency field '{field.name}' to '{_node_name(declaration, source)}'; "
            "constructor or setter injection must be wired by hand."
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

    found = _find_field(declaration, operation.original_name or operation.field_name or field.name, source)
    if found is None:
        raise _Skip(
            f"field '{operation.original_name or operation.field_name or field.name}' was not found."
        )

    member, declarator = found
    old_name = node_text(source, declarator.child_by_field_name("name")).strip()
    if not old_name:
        raise _Skip("the target field has no resolvable name.")

    indent = line_indent(source, member.start_byte)
    if indent is None:
        indent = detect_member_indent(source, _body(declaration), "").text

    edits: list[tuple[int, int, bytes]] = []
    eol = line_ending(source)

    modifier_text = _modifier_replacement(member, field, indent, eol)
    modifiers = _modifiers(member)
    if modifiers is not None:
        if modifier_text is not None:
            edits.append((modifiers.start_byte, modifiers.end_byte, modifier_text.encode("utf-8")))
    elif modifier_text:
        prefix = modifier_text if modifier_text[-1].isspace() else f"{modifier_text} "
        edits.append((member.start_byte, member.start_byte, prefix.encode("utf-8")))

    type_node = member.child_by_field_name("type")
    if type_node is not None and field.type.strip() and node_text(source, type_node).strip() != field.type.strip():
        edits.append((type_node.start_byte, type_node.end_byte, field.type.strip().encode("utf-8")))

    name_node = declarator.child_by_field_name("name")
    if name_node is not None and old_name != field.name.strip():
        edits.append((name_node.start_byte, name_node.end_byte, field.name.strip().encode("utf-8")))

    note = None
    if old_name != field.name.strip():
        renamed = _reference_rename_edits(
            source,
            declaration,
            old_name,
            field.name.strip(),
            member,
            name_node,
        )
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

    found = _find_field(declaration, field_name, source)
    if found is None:
        raise _Skip(f"field '{field_name}' was not found.")

    member, _declarator = found
    variables = [child for child in member.children if child.type == "variable_declarator"]
    if len(variables) > 1:
        raise _Skip(
            f"'{field_name}' shares a multi-variable declaration; only single-variable fields are removed surgically."
        )

    start = line_start(source, member.start_byte)
    if source[start:member.start_byte].strip(b" \t") != b"":
        start = member.start_byte
    end = line_removal_end(source, member.end_byte)
    return splice(source, [(start, end, b"")]), None


def _add_annotation(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    annotation = _normalize_annotation(operation.annotation)
    if not annotation:
        raise _Skip("annotation is required.")

    target: Node = declaration
    if operation.field_name:
        found = _find_field(declaration, operation.field_name, source)
        if found is None:
            raise _Skip(f"field '{operation.field_name}' was not found.")
        target = found[0]

    if any(_annotation_name(node, source) == _annotation_name_text(annotation) for node in _annotations(target)):
        raise _Skip(f"annotation {annotation} is already present.")

    indent = detect_type_indent(source, target)
    insertion = f"{annotation}{line_ending(source)}{indent}".encode()
    return splice(source, [(target.start_byte, target.start_byte, insertion)]), None


def _remove_annotation(
    source: bytes,
    declaration: Node,
    operation: PatchOperation,
) -> tuple[bytes, None]:
    name = _annotation_name_text(operation.annotation)
    if not name:
        raise _Skip("annotation is required.")

    target: Node = declaration
    if operation.field_name:
        found = _find_field(declaration, operation.field_name, source)
        if found is None:
            raise _Skip(f"field '{operation.field_name}' was not found.")
        target = found[0]

    match = next(
        (node for node in _annotations(target) if _annotation_name(node, source) == name),
        None,
    )
    if match is None:
        raise _Skip(f"annotation {operation.annotation} was not found.")

    start = line_start(source, match.start_byte)
    prefix = source[start:match.start_byte]
    end_of_line = line_end(source, match.end_byte)
    suffix = source[match.end_byte:end_of_line]

    if prefix.strip(b" \t") == b"" and suffix.strip(b" \t") == b"":
        return splice(source, [(start, line_removal_end(source, match.end_byte), b"")]), None

    end = match.end_byte
    while end < len(source) and source[end : end + 1] in {b" ", b"\t"}:
        end += 1
    return splice(source, [(match.start_byte, end, b"")]), None


def _modifier_replacement(
    member: Node,
    field: PatchField,
    indent: str,
    eol: str,
) -> str | None:
    annotations = [_normalize_annotation(item) for item in field.annotations]
    annotations = [item for item in annotations if item]
    visibility = _java_visibility(field.visibility)
    others = _other_modifiers(member)

    parts = [*annotations]
    modifier_keywords = " ".join(item for item in [visibility, *others] if item)
    if modifier_keywords:
        parts.append(modifier_keywords)
    if not parts:
        return None

    joined = (eol + indent).join(parts)
    if annotations and not modifier_keywords:
        return f"{joined}{eol}{indent}"
    return joined


def _reference_rename_edits(
    source: bytes,
    declaration: Node,
    old_name: str,
    new_name: str,
    target_member: Node,
    target_name: Node | None,
) -> list[tuple[int, int, bytes]]:
    edits: list[tuple[int, int, bytes]] = []
    replacement = new_name.encode("utf-8")

    for node in walk(declaration):
        if node.type != "identifier" or node_text(source, node) != old_name:
            continue
        if target_name is not None and node.start_byte == target_name.start_byte:
            continue
        if node.start_byte >= target_member.start_byte and node.end_byte <= target_member.end_byte:
            continue

        parent = node.parent
        if parent is not None:
            declaration_name = parent.child_by_field_name("name")
            if (
                parent.type in _DECLARATION_NAME_PARENTS
                and declaration_name is not None
                and declaration_name.start_byte == node.start_byte
            ):
                continue
            if parent.type in _ANNOTATION_TYPES:
                continue
            if (
                parent.type == "method_invocation"
                and declaration_name is not None
                and declaration_name.start_byte == node.start_byte
            ):
                continue

        edits.append((node.start_byte, node.end_byte, replacement))

    return edits


def _render_field_lines(field: PatchField, indent: str, *, dependency: bool) -> list[str]:
    annotations = [_normalize_annotation(item) for item in field.annotations]
    annotations = [item for item in annotations if item]
    visibility = _java_visibility(field.visibility)
    if dependency and not visibility:
        visibility = "private"

    type_text = field.type.strip() or "Object"
    modifiers = f"{visibility} " if visibility else ""
    lines = [f"{indent}{annotation}" for annotation in annotations]
    lines.append(f"{indent}{modifiers}{type_text} {field.name.strip()};")
    return lines


def _java_visibility(value: str | None) -> str:
    for word in (value or "").split():
        if word in {"public", "protected", "private"}:
            return word
    return ""


def _other_modifiers(member: Node) -> list[str]:
    modifiers = _modifiers(member)
    if modifiers is None:
        return []
    others: list[str] = []
    for child in modifiers.children:
        if child.type in _ANNOTATION_TYPES:
            continue
        text = child.type
        if text in {"public", "protected", "private"}:
            continue
        if text in {"static", "final", "transient", "volatile"}:
            others.append(text)
    return others


def _annotations(member: Node) -> list[Node]:
    modifiers = _modifiers(member)
    if modifiers is None:
        return []
    return [child for child in modifiers.children if child.type in _ANNOTATION_TYPES]


def _modifiers(member: Node) -> Node | None:
    return next((child for child in member.children if child.type == "modifiers"), None)


def _annotation_name(node: Node, source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    raw = node_text(source, name_node) if name_node is not None else node_text(source, node)
    return _annotation_name_text(raw)


def _annotation_name_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = text.split("(", 1)[0].strip().lstrip("@[")
    text = text.removesuffix("]")
    return text.split(".")[-1].strip()


def _normalize_annotation(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("["):
        text = text.strip("[]").strip()
    if not text.startswith("@"):
        text = f"@{text.lstrip('@')}"
    return text


def _find_type(root: Node, type_name: str, source: bytes) -> Node | None:
    for node in walk(root):
        if node.type in _JAVA_TYPES and _node_name(node, source) == type_name:
            return node
    return None


def _node_name(node: Node, source: bytes) -> str:
    return node_text(source, node.child_by_field_name("name")).strip()


def _body(declaration: Node) -> Node:
    body = declaration.child_by_field_name("body")
    if body is None:
        raise _Skip("the target type has no body.")
    return body


def _field_members(body: Node) -> list[Node]:
    return [child for child in body.children if child.type == "field_declaration"]


def _find_field(declaration: Node, name: str, source: bytes) -> tuple[Node, Node] | None:
    body = declaration.child_by_field_name("body")
    if body is None:
        return None
    for member in _field_members(body):
        for child in member.children:
            if child.type != "variable_declarator":
                continue
            if node_text(source, child.child_by_field_name("name")).strip() == name:
                return member, child
    return None


def _import_names_for(operation: PatchOperation) -> set[str]:
    names: set[str] = set()
    if operation.field is not None:
        names.update(_IDENTIFIER_RE.findall(operation.field.type))
        for annotation in operation.field.annotations:
            name = _annotation_name_text(annotation)
            if name:
                names.add(name)
    if operation.annotation:
        name = _annotation_name_text(operation.annotation)
        if name:
            names.add(name)
    return names


def _ensure_imports(source: bytes, names: set[str]) -> tuple[bytes, list[str]]:
    text = source.decode("utf-8", errors="replace")
    existing = {match.group(1) for match in _IMPORT_RE.finditer(text)}
    wildcard_packages = {value.removesuffix(".*") for value in existing if value.endswith(".*")}
    eol = "\r\n" if "\r\n" in text else "\n"

    candidates: list[str] = []
    for name in sorted(names):
        fqn = _IMPORT_MAP.get(name)
        if fqn is None or fqn in existing:
            continue
        package = fqn.rsplit(".", 1)[0]
        if package in wildcard_packages:
            continue
        if fqn not in candidates:
            candidates.append(fqn)

    if not candidates:
        return source, []

    lines = [f"import {fqn};" for fqn in sorted(candidates)]
    matches = list(_IMPORT_RE.finditer(text))
    if matches:
        position = matches[-1].end()
        insertion = eol + eol.join(lines)
    else:
        package = _PACKAGE_RE.search(text)
        if package is not None:
            position = package.end()
            insertion = eol + eol + eol.join(lines)
        else:
            position = 0
            insertion = eol.join(lines) + eol + eol

    updated = text[:position] + insertion + text[position:]
    return updated.encode("utf-8"), []


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
