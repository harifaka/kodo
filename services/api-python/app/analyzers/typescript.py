"""TypeScript / JavaScript / Node.js analyzer built on tree-sitter-typescript and tree-sitter-javascript."""

from __future__ import annotations

import functools
import posixpath
from dataclasses import dataclass, field

import tree_sitter_javascript
import tree_sitter_typescript
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

SCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_IMPORT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

_CLASS_NODE_TYPES = frozenset({"class_declaration", "abstract_class_declaration"})
_FUNCTION_NODE_TYPES = frozenset({"function_declaration", "generator_function_declaration"})
_FIELD_NODE_TYPES = frozenset({"public_field_definition", "property_declaration", "field_definition"})
_IDENTIFIER_NODE_TYPES = frozenset({"identifier", "property_identifier", "type_identifier"})


@dataclass
class _Import:
    module: str
    names: list[str] = field(default_factory=list)


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


def _language_kind(rel_path: str) -> str:
    lowered = rel_path.lower()
    if lowered.endswith(".tsx"):
        return "tsx"
    if lowered.endswith((".ts", ".mts", ".cts")):
        return "ts"
    return "js"


class _Source:
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def parse_script(rel_path: str, source: bytes, known_files: set[str] | None = None) -> ParseResult:
    result = ParseResult()
    src = _Source(source)
    tree = _parser(_language_kind(rel_path)).parse(source)
    root = tree.root_node

    if root.has_error:
        result.warnings.append(
            f"TypeScript/JavaScript: parse errors in {rel_path}; the file's architecture may be incomplete."
        )

    imports: list[_Import] = []
    for child in root.children:
        _collect_statement(child, rel_path, src, result, imports, exported=False, decorators=[])

    if not result.nodes and source.strip():
        name = posixpath.splitext(posixpath.basename(rel_path))[0] or rel_path
        result.nodes.append(
            ComponentNode(
                id=rel_path,
                name=name,
                stack=Stack.NODEJS,
                layer=Layer.OTHER,
                kind=NodeKind.MODULE,
                file_path=rel_path,
                annotations=[],
                fields=[],
                methods=[],
            )
        )

    _attach_imports(rel_path, imports, result, known_files or set())
    return result


def _collect_statement(
    node: Node,
    rel_path: str,
    src: _Source,
    result: ParseResult,
    imports: list[_Import],
    *,
    exported: bool,
    decorators: list[str],
) -> None:
    if node.type == "import_statement":
        imports.append(_read_import(node, src))
        return

    if node.type == "export_statement":
        collected = decorators + [_decorator_text(child, src) for child in node.children if child.type == "decorator"]
        for child in node.children:
            _collect_statement(
                child,
                rel_path,
                src,
                result,
                imports,
                exported=True,
                decorators=dedupe([d for d in collected if d]),
            )
        return

    if node.type in _CLASS_NODE_TYPES:
        _collect_class(node, rel_path, src, result, decorators)
    elif node.type == "interface_declaration":
        _collect_interface(node, rel_path, src, result)
    elif node.type == "enum_declaration":
        name = src.text(node.child_by_field_name("name")).strip()
        _add_node(node, rel_path, name, NodeKind.ENUM, [], [], [], result)
    elif node.type in _FUNCTION_NODE_TYPES and exported:
        _collect_function(node, rel_path, src, result, decorators)
    elif node.type == "lexical_declaration" and exported:
        _collect_arrow_functions(node, rel_path, src, result, decorators)


def _collect_class(
    node: Node,
    rel_path: str,
    src: _Source,
    result: ParseResult,
    decorators: list[str],
) -> None:
    name = src.text(node.child_by_field_name("name")).strip()
    if not name:
        return

    node_id = f"{rel_path}#{name}"
    annotations = dedupe(decorators + [_decorator_text(c, src) for c in node.children if c.type == "decorator"])
    fields: list[ComponentField] = []
    methods: list[ComponentMethod] = []

    body = node.child_by_field_name("body")
    for member in body.children if body is not None else []:
        if member.type in _FIELD_NODE_TYPES:
            type_text = _type_text(member.child_by_field_name("type"), src)
            fields.append(
                ComponentField(
                    name=src.text(member.child_by_field_name("name")).strip(),
                    type=type_text,
                    visibility=_accessibility(member, src) or "public",
                    annotations=[_decorator_text(c, src) for c in member.children if c.type == "decorator"],
                )
            )
            _add_type_references(result, node_id, type_text, RelationType.DEPENDS_ON)
        elif member.type == "method_definition":
            method, signature_types = _read_method(member, src)
            methods.append(method)
            for type_text in signature_types:
                _add_type_references(result, node_id, type_text, RelationType.REFERENCES)

            if method.name == "constructor":
                for type_text, param_name, accessibility in _parameters(member, src):
                    if accessibility:
                        fields.append(
                            ComponentField(name=param_name, type=type_text, visibility=accessibility, annotations=[])
                        )
                    _add_type_references(result, node_id, type_text, RelationType.DEPENDS_ON)

    for base_name in _heritage(node, src):
        result.references.append(ReferenceCandidate(node_id, base_name, BASE_RELATION))

    layer = _infer_layer(name, rel_path)
    result.nodes.append(
        ComponentNode(
            id=node_id,
            name=name,
            stack=Stack.NODEJS,
            layer=layer,
            kind=NodeKind.CLASS,
            file_path=rel_path,
            annotations=annotations,
            fields=fields,
            methods=methods,
        )
    )


def _collect_interface(node: Node, rel_path: str, src: _Source, result: ParseResult) -> None:
    name = src.text(node.child_by_field_name("name")).strip()
    if not name:
        return

    node_id = f"{rel_path}#{name}"
    fields: list[ComponentField] = []
    methods: list[ComponentMethod] = []

    body = node.child_by_field_name("body")
    for member in body.children if body is not None else []:
        if member.type == "property_signature":
            fields.append(
                ComponentField(
                    name=src.text(member.child_by_field_name("name")).strip(),
                    type=_type_text(member.child_by_field_name("type"), src),
                    visibility="public",
                    annotations=[],
                )
            )
        elif member.type == "method_signature":
            method, _ = _read_method(member, src)
            methods.append(method)

    for base_name in _heritage(node, src):
        result.references.append(ReferenceCandidate(node_id, base_name, BASE_RELATION))

    result.nodes.append(
        ComponentNode(
            id=node_id,
            name=name,
            stack=Stack.NODEJS,
            layer=_infer_layer(name, rel_path),
            kind=NodeKind.INTERFACE,
            file_path=rel_path,
            annotations=[],
            fields=fields,
            methods=methods,
        )
    )


def _collect_function(
    node: Node,
    rel_path: str,
    src: _Source,
    result: ParseResult,
    decorators: list[str],
) -> None:
    name = src.text(node.child_by_field_name("name")).strip()
    if not name:
        return

    parameters = _parameters(node, src)
    _add_node(
        node,
        rel_path,
        name,
        NodeKind.MODULE,
        decorators,
        [],
        [
            ComponentMethod(
                name=name,
                return_type=_type_text(node.child_by_field_name("return_type"), src) or None,
                parameters=[render_parameter(type_text, param_name) for type_text, param_name, _ in parameters],
            )
        ],
        result,
    )
    node_id = f"{rel_path}#{name}"
    for type_text, _, _ in parameters:
        _add_type_references(result, node_id, type_text, RelationType.REFERENCES)
    _add_type_references(
        result,
        node_id,
        _type_text(node.child_by_field_name("return_type"), src),
        RelationType.REFERENCES,
    )


def _collect_arrow_functions(
    node: Node,
    rel_path: str,
    src: _Source,
    result: ParseResult,
    decorators: list[str],
) -> None:
    for declarator in (child for child in node.children if child.type == "variable_declarator"):
        value = declarator.child_by_field_name("value")
        if value is None or value.type not in {"arrow_function", "function_expression"}:
            continue

        name = src.text(declarator.child_by_field_name("name")).strip()
        if not name:
            continue

        node_id = f"{rel_path}#{name}"
        parameters = _parameters(value, src)
        result.nodes.append(
            ComponentNode(
                id=node_id,
                name=name,
                stack=Stack.NODEJS,
                layer=_infer_layer(name, rel_path),
                kind=NodeKind.MODULE,
                file_path=rel_path,
                annotations=decorators,
                fields=[],
                methods=[
                    ComponentMethod(
                        name=name,
                        return_type=_type_text(value.child_by_field_name("return_type"), src) or None,
                        parameters=[render_parameter(t, n) for t, n, _ in parameters],
                    )
                ],
            )
        )
        for type_text, _, _ in parameters:
            _add_type_references(result, node_id, type_text, RelationType.REFERENCES)


def _add_node(
    node: Node,
    rel_path: str,
    name: str,
    kind: NodeKind,
    annotations: list[str],
    fields: list[ComponentField],
    methods: list[ComponentMethod],
    result: ParseResult,
) -> None:
    if not name:
        return
    result.nodes.append(
        ComponentNode(
            id=f"{rel_path}#{name}",
            name=name,
            stack=Stack.NODEJS,
            layer=_infer_layer(name, rel_path),
            kind=kind,
            file_path=rel_path,
            annotations=dedupe(annotations),
            fields=fields,
            methods=methods,
        )
    )


def _read_method(node: Node, src: _Source) -> tuple[ComponentMethod, list[str]]:
    parameters = _parameters(node, src)
    method = ComponentMethod(
        name=src.text(node.child_by_field_name("name")).strip(),
        return_type=_type_text(node.child_by_field_name("return_type"), src) or None,
        parameters=[render_parameter(type_text, name) for type_text, name, _ in parameters],
    )
    signature_types = [type_text for type_text, _, _ in parameters]
    signature_types.append(method.return_type or "")
    return method, signature_types


def _parameters(node: Node, src: _Source) -> list[tuple[str, str, str | None]]:
    params = node.child_by_field_name("parameters")
    if params is None:
        return []

    entries: list[tuple[str, str, str | None]] = []
    for param in params.children:
        if param.type not in {"required_parameter", "optional_parameter"}:
            continue
        type_text = _type_text(param.child_by_field_name("type"), src)
        name = _parameter_name(param, src)
        accessibility = _accessibility(param, src)
        if name:
            entries.append((type_text, name, accessibility))
    return entries


def _parameter_name(node: Node, src: _Source) -> str:
    named = node.child_by_field_name("name")
    if named is not None:
        return src.text(named).strip()
    for child in node.children:
        if child.type in _IDENTIFIER_NODE_TYPES:
            return src.text(child).strip()
    return ""


def _heritage(node: Node, src: _Source) -> list[str]:
    names: list[str] = []

    extends_types = next((child for child in node.children if child.type == "extends_type_clause"), None)
    if extends_types is not None:
        for child in extends_types.children:
            if child.type in {"type_identifier", "generic_type", "identifier"}:
                name = base_type_name(src.text(child))
                if name:
                    names.append(name)

    heritage = next((child for child in node.children if child.type == "class_heritage"), None)
    if heritage is None:
        return names

    for clause in heritage.children:
        if clause.type == "extends_clause":
            value = clause.child_by_field_name("value")
            if value is None:
                value = next((child for child in clause.children if child.type in _IDENTIFIER_NODE_TYPES), None)
            name = base_type_name(src.text(value))
            if name:
                names.append(name)
        elif clause.type == "implements_clause":
            for child in clause.children:
                if child.type in {"type_identifier", "generic_type", "identifier"}:
                    name = base_type_name(src.text(child))
                    if name:
                        names.append(name)
    return names


def _read_import(node: Node, src: _Source) -> _Import:
    module = src.text(node.child_by_field_name("source")).strip().strip("'\"")
    names: list[str] = []
    for child in node.children:
        if child.type == "import_clause":
            for part in child.children:
                if part.type == "identifier":
                    names.append(src.text(part).strip())
                elif part.type == "named_imports":
                    for specifier in part.children:
                        if specifier.type == "import_specifier":
                            name = src.text(specifier.child_by_field_name("name")).strip()
                            if name:
                                names.append(name)
    return _Import(module=module, names=names)


def _attach_imports(
    rel_path: str,
    imports: list[_Import],
    result: ParseResult,
    known_files: set[str],
) -> None:
    if not result.nodes:
        return

    primary_id = result.nodes[0].id
    for imported in imports:
        target_file = _resolve_import(rel_path, imported.module, known_files)
        if target_file is None:
            continue

        for symbol in imported.names or [""]:
            result.references.append(
                ReferenceCandidate(primary_id, symbol, RelationType.REFERENCES, file_hint=target_file)
            )


def _resolve_import(rel_path: str, specifier: str, known_files: set[str]) -> str | None:
    if not specifier.startswith("."):
        return None

    base = posixpath.normpath(posixpath.join(posixpath.dirname(rel_path), specifier))
    if base in known_files and posixpath.splitext(base)[1] in _IMPORT_EXTENSIONS:
        return base

    for extension in _IMPORT_EXTENSIONS:
        candidate = f"{base}{extension}"
        if candidate in known_files:
            return candidate
    for extension in _IMPORT_EXTENSIONS:
        candidate = f"{base}/index{extension}"
        if candidate in known_files:
            return candidate
    return None


def _type_text(node: Node | None, src: _Source) -> str:
    if node is None:
        return ""
    return normalize_type(src.text(node))


def _add_type_references(result: ParseResult, source_id: str, type_text: str, relation: RelationType) -> None:
    for identifier in type_identifiers(type_text):
        result.references.append(ReferenceCandidate(source_id, identifier, relation))


def _accessibility(node: Node, src: _Source) -> str | None:
    for child in node.children:
        if child.type == "accessibility_modifier":
            return src.text(child).strip()
    return None


def _decorator_text(node: Node, src: _Source) -> str:
    raw = src.text(node).strip()
    if not raw:
        return ""
    return normalize_annotation(raw.lstrip("@"), style="at")


def _infer_layer(name: str, rel_path: str) -> Layer:
    path = rel_path.replace("\\", "/").lower()

    if name.endswith("Controller"):
        return Layer.CONTROLLER
    if name.endswith("Service"):
        return Layer.SERVICE
    if name.endswith(("Repository", "Repo")):
        return Layer.REPOSITORY
    if name.endswith("ViewModel"):
        return Layer.VIEWMODEL
    if name.endswith("Entity"):
        return Layer.ENTITY
    if "/views/" in path or "/pages/" in path:
        return Layer.VIEW
    if "/components/" in path:
        return Layer.COMPONENT
    if path.endswith((".tsx", ".jsx")) and name[:1].isupper():
        return Layer.COMPONENT
    return Layer.OTHER
