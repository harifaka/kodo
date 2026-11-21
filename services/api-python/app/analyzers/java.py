"""Java / Spring Boot analyzer built on tree-sitter-java."""

from __future__ import annotations

import functools

import tree_sitter_java
from tree_sitter import Language, Node, Parser

from app.analyzers.common import (
    BASE_RELATION,
    ParseResult,
    ReferenceCandidate,
    base_type_name,
    dedupe,
    normalize_annotation,
    normalize_type,
    render_parameter,
    type_identifiers,
)
from app.models.ir import (
    ComponentField,
    ComponentMethod,
    ComponentNode,
    Layer,
    NodeKind,
    RelationType,
    Stack,
)

KIND_BY_NODE: dict[str, NodeKind] = {
    "class_declaration": NodeKind.CLASS,
    "interface_declaration": NodeKind.INTERFACE,
    "enum_declaration": NodeKind.ENUM,
    "record_declaration": NodeKind.RECORD,
    "annotation_type_declaration": NodeKind.INTERFACE,
}

TYPE_DECLARATIONS = frozenset(KIND_BY_NODE)

CONTROLLER_ANNOTATIONS = frozenset({"@RestController", "@Controller"})
ENTITY_ANNOTATIONS = frozenset({"@Entity", "@Table", "@Document", "@MappedSuperclass", "@Embeddable"})

_TYPE_CHILD_TYPES = frozenset(
    {
        "type_identifier",
        "scoped_type_identifier",
        "generic_type",
        "array_type",
        "primitive_type",
        "floating_point_type",
        "integral_type",
        "boolean_type",
        "void_type",
    }
)


@functools.lru_cache(maxsize=1)
def _parser() -> Parser:
    return Parser(Language(tree_sitter_java.language()))


class _Source:
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def parse_java(rel_path: str, source: bytes) -> ParseResult:
    result = ParseResult()
    src = _Source(source)
    tree = _parser().parse(source)
    root = tree.root_node

    if root.has_error:
        result.warnings.append(f"Java: parse errors in {rel_path}; the file's architecture may be incomplete.")

    package = ""
    for child in root.children:
        if child.type == "package_declaration":
            package = src.text(_first(child, {"scoped_identifier", "identifier"}))
            break

    for child in root.children:
        _collect(child, package, rel_path, src, result)

    return result


def _collect(node: Node, scope: str, rel_path: str, src: _Source, result: ParseResult) -> None:
    if node.type in TYPE_DECLARATIONS:
        _collect_type(node, scope, rel_path, src, result)


def _collect_type(node: Node, scope: str, rel_path: str, src: _Source, result: ParseResult) -> None:
    name = src.text(node.child_by_field_name("name")).strip()
    if not name:
        return

    node_id = f"{scope}.{name}" if scope else name
    kind = KIND_BY_NODE[node.type]
    annotations = _annotations(node, src)
    fields: list[ComponentField] = []
    methods: list[ComponentMethod] = []

    for base_name in _base_type_names(node, src):
        result.references.append(ReferenceCandidate(node_id, base_name, BASE_RELATION))

    body = node.child_by_field_name("body")
    if body is not None:
        for member in body.children:
            if member.type == "field_declaration":
                fields.extend(_collect_field(member, node_id, src, result))
            elif member.type == "method_declaration":
                method, references = _collect_method(member, src)
                methods.append(method)
                result.references.extend(
                    ReferenceCandidate(node_id, ref, RelationType.REFERENCES) for ref in references
                )
            elif member.type == "constructor_declaration":
                for type_text in _parameter_types(member, src):
                    result.references.extend(
                        ReferenceCandidate(node_id, ref, RelationType.DEPENDS_ON)
                        for ref in type_identifiers(type_text)
                    )
            elif member.type in TYPE_DECLARATIONS:
                _collect_type(member, node_id, rel_path, src, result)

    # Java records declare their components as constructor parameters.
    for param in _parameter_nodes(node):
        type_text = _declared_type(param, src)
        param_name = src.text(param.child_by_field_name("name")).strip()
        if not type_text or not param_name:
            continue
        fields.append(
            ComponentField(
                name=param_name,
                type=normalize_type(type_text),
                visibility="private",
                annotations=_parameter_annotations(param, src),
            )
        )
        result.references.extend(
            ReferenceCandidate(node_id, ref, RelationType.DEPENDS_ON) for ref in type_identifiers(type_text)
        )

    layer = _infer_layer(name, annotations)
    result.nodes.append(
        ComponentNode(
            id=node_id,
            name=name,
            stack=Stack.SPRING_BOOT,
            layer=layer,
            kind=kind,
            file_path=rel_path,
            annotations=annotations,
            fields=fields,
            methods=methods,
        )
    )


def _collect_field(node: Node, owner_id: str, src: _Source, result: ParseResult) -> list[ComponentField]:
    type_text = normalize_type(_declared_type(node, src))
    if not type_text:
        return []

    annotations = _annotations(node, src)
    visibility = _visibility(node, src)
    fields: list[ComponentField] = []

    for declarator in (child for child in node.children if child.type == "variable_declarator"):
        field_name = src.text(declarator.child_by_field_name("name")).strip()
        if not field_name:
            continue
        fields.append(
            ComponentField(name=field_name, type=type_text, visibility=visibility, annotations=annotations)
        )

    result.references.extend(
        ReferenceCandidate(owner_id, ref, RelationType.DEPENDS_ON) for ref in type_identifiers(type_text)
    )
    return fields


def _collect_method(node: Node, src: _Source) -> tuple[ComponentMethod, list[str]]:
    parameters = _parameters(node, src)
    method = ComponentMethod(
        name=src.text(node.child_by_field_name("name")).strip(),
        return_type=normalize_type(src.text(node.child_by_field_name("type"))) or None,
        parameters=[render_parameter(type_text, name) for type_text, name in parameters],
    )

    referenced = [method.return_type or ""]
    referenced.extend(type_text for type_text, _ in parameters)

    references: list[str] = []
    for type_text in referenced:
        references.extend(type_identifiers(type_text))
    return method, references


def _parameters(node: Node, src: _Source) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for param in _parameter_nodes(node):
        type_text = _declared_type(param, src)
        name = src.text(param.child_by_field_name("name")).strip()
        if type_text:
            entries.append((type_text, name))
    return entries


def _parameter_nodes(node: Node) -> list[Node]:
    params = node.child_by_field_name("parameters")
    if params is None:
        return []
    return [param for param in params.children if param.type in {"formal_parameter", "spread_parameter"}]


def _parameter_types(node: Node, src: _Source) -> list[str]:
    return [type_text for type_text, _ in _parameters(node, src)]


def _declared_type(node: Node, src: _Source) -> str:
    declared = node.child_by_field_name("type")
    if declared is not None:
        return src.text(declared)
    for child in node.children:
        if child.type in _TYPE_CHILD_TYPES:
            return src.text(child)
    return ""


def _base_type_names(node: Node, src: _Source) -> list[str]:
    names: list[str] = []
    superclass = node.child_by_field_name("superclass")
    if superclass is not None:
        names.extend(_type_node_names(superclass, src))

    for child in node.children:
        if child.type in {"super_interfaces", "extends_interfaces"}:
            names.extend(_type_node_names(child, src))
    return names


def _type_node_names(node: Node, src: _Source) -> list[str]:
    names: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in {"type_identifier", "scoped_type_identifier", "generic_type"}:
            name = base_type_name(src.text(current))
            if name:
                names.append(name)
            continue
        stack.extend(reversed(current.children))
    return names


def _annotations(node: Node, src: _Source) -> list[str]:
    modifiers = _first(node, {"modifiers"})
    if modifiers is None:
        return []
    return _annotations_in(modifiers, src)


def _parameter_annotations(node: Node, src: _Source) -> list[str]:
    """Annotations on a formal parameter — record components carry the DTO validation constraints."""
    modifiers = _first(node, {"modifiers"})
    if modifiers is None:
        return []
    return _annotations_in(modifiers, src)


def _annotations_in(modifiers: Node, src: _Source) -> list[str]:
    annotations: list[str] = []
    for child in modifiers.children:
        if child.type not in {"annotation", "marker_annotation"}:
            continue
        name_node = child.child_by_field_name("name")
        raw = src.text(name_node) if name_node is not None else src.text(child)
        normalized = normalize_annotation(raw, style="at")
        if normalized:
            annotations.append(normalized)
    return dedupe(annotations)


def _visibility(node: Node, src: _Source) -> str:
    modifiers = _first(node, {"modifiers"})
    if modifiers is None:
        return "package"
    text = src.text(modifiers)
    for keyword in ("public", "protected", "private"):
        if keyword in text.split():
            return keyword
    return "package"


def _first(node: Node, types: set[str]) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _infer_layer(name: str, annotations: list[str]) -> Layer:
    annotation_set = set(annotations)

    if annotation_set & CONTROLLER_ANNOTATIONS:
        return Layer.CONTROLLER
    if "@Service" in annotation_set:
        return Layer.SERVICE
    if "@Repository" in annotation_set:
        return Layer.REPOSITORY
    if annotation_set & ENTITY_ANNOTATIONS:
        return Layer.ENTITY

    if name.endswith("Controller"):
        return Layer.CONTROLLER
    if name.endswith("Service"):
        return Layer.SERVICE
    if name.endswith(("Repository", "Dao", "Repo")):
        return Layer.REPOSITORY
    if name.endswith(("Entity", "Document")):
        return Layer.ENTITY
    return Layer.OTHER


__all__ = ["parse_java"]
