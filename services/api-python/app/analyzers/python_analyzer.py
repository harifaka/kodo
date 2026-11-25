"""Python / FastAPI / Django / Flask analyzer built on tree-sitter-python (Phase 12).

The analyzer is pure: ``parse_python(rel_path, source)`` returns Core IR nodes and unresolved
references. Classes become components; module-level ``APIRouter`` / ``FastAPI`` / ``Blueprint``
route modules become synthetic ``router`` components so real FastAPI/Flask apps map onto the
Macro Graph.

DTOs intentionally use the Core IR ``other`` layer: the canonical contract has no dedicated
``dto`` layer, and the audit engine already identifies payloads by name + validation markers.
"""

from __future__ import annotations

import functools
import posixpath
import re

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from app.analyzers.common import (
    BASE_RELATION,
    ParseResult,
    ReferenceCandidate,
    base_type_name,
    dedupe,
    normalize_type,
    type_identifiers,
)
from app.analyzers.python_imports import import_hints
from app.analyzers.python_layers import infer_kind, infer_layer
from app.models.ir import (
    ComponentField,
    ComponentMethod,
    ComponentNode,
    Layer,
    NodeKind,
    RelationType,
    Stack,
)

_ROUTER_FACTORIES = frozenset({"APIRouter", "FastAPI", "Blueprint"})
_ROUTER_DECORATORS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "route", "websocket", "api_route"}
)
_DJANGO_VIEW_DECORATORS = frozenset({"api_view", "action"})
_GENERIC_ROUTE_STEMS = frozenset({"routes", "views", "urls", "endpoints", "api", "__init__"})

_FIELD_CALL_ANNOTATIONS = frozenset(
    {"Field", "Column", "mapped_column", "relationship", "ForeignKey", "Index"}
)

_ORM_FIELD_TYPES = {
    "CharField": "str",
    "TextField": "str",
    "EmailField": "str",
    "SlugField": "str",
    "URLField": "str",
    "IntegerField": "int",
    "BigIntegerField": "int",
    "SmallIntegerField": "int",
    "AutoField": "int",
    "FloatField": "float",
    "DecimalField": "Decimal",
    "BooleanField": "bool",
    "DateTimeField": "datetime",
    "DateField": "date",
    "TimeField": "time",
    "UUIDField": "UUID",
    "JSONField": "dict",
}

_COLUMN_TYPE_ALIASES = {
    "String": "str",
    "Text": "str",
    "Unicode": "str",
    "Integer": "int",
    "BigInteger": "int",
    "SmallInteger": "int",
    "Float": "float",
    "Numeric": "Decimal",
    "Boolean": "bool",
    "DateTime": "datetime",
    "Date": "date",
    "Time": "time",
    "UUID": "UUID",
    "JSON": "dict",
}

# Builtins and typing helpers never resolve to a discovered component.
_PYTHON_NON_TYPES = frozenset(
    {
        "list", "dict", "set", "tuple", "frozenset", "str", "int", "float", "bool", "bytes",
        "object", "type", "Any", "Optional", "Union", "None", "Ellipsis", "self", "cls",
        "Mapped", "mapped_column", "relationship", "Column", "Field", "ForeignKey", "Index",
        "Sequence", "Mapping", "Iterable", "Iterator", "Callable", "Literal", "ClassVar",
        "Annotated", "TypeVar", "Generic", "Decimal", "datetime", "date", "time", "UUID",
        "Depends", "Body", "Query", "Path", "Header", "Form", "File", "Request", "Response",
        "awaitable", "coroutine", "Generator", "AsyncIterator", "AsyncGenerator",
    }
)

_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DUNDER_RE = re.compile(r"^__[A-Za-z0-9_]+__$")


@functools.lru_cache(maxsize=1)
def _parser() -> Parser:
    return Parser(Language(tree_sitter_python.language()))


class _Source:
    __slots__ = ("data",)

    def __init__(self, data: bytes) -> None:
        self.data = data

    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def parse_python(
    rel_path: str,
    source: bytes,
    known_files: set[str] | None = None,
) -> ParseResult:
    result = ParseResult()
    src = _Source(source)
    root = _parser().parse(source).root_node

    if root.has_error:
        result.warnings.append(
            f"Python: parse errors in {rel_path}; the file's architecture may be incomplete."
        )

    module_id = _module_id(rel_path)
    index_hints = import_hints(root, module_id, known_files or set(), src.text)

    for statement in _statements(root):
        definition, decorators = _definition(statement, src)
        if definition is None or definition.type != "class_definition":
            continue
        _collect_class(definition, decorators, module_id, rel_path, src, result, index_hints)

    _collect_module_router(root, rel_path, src, result, index_hints)

    return result


# ------------------------------------------------------------------------------- classes


def _collect_class(
    node: Node,
    decorators: list[str],
    scope: str,
    rel_path: str,
    src: _Source,
    result: ParseResult,
    hints: dict[str, str],
) -> None:
    name = src.text(node.child_by_field_name("name")).strip()
    if not name:
        return

    node_id = f"{scope}.{name}"
    bases = _base_names(node, src)
    annotations = dedupe(decorators)
    for base_name in bases:
        result.references.append(
            ReferenceCandidate(node_id, base_name, BASE_RELATION, hints.get(base_name))
        )

    fields: list[ComponentField] = []
    methods: list[ComponentMethod] = []
    body = node.child_by_field_name("body")
    if body is not None:
        for item in _statements(body):
            definition, item_decorators = _definition(item, src)
            if definition is None:
                continue
            if definition.type == "class_definition":
                _collect_class(definition, item_decorators, node_id, rel_path, src, result, hints)
            elif definition.type == "function_definition":
                method, method_fields = _collect_method(definition, node_id, src, result, hints)
                methods.append(method)
                fields.extend(method_fields)
            elif definition.type == "assignment":
                fields.extend(_collect_class_attribute(definition, node_id, src, result, hints))

    layer = infer_layer(name, bases, annotations, rel_path, fields)
    kind = infer_kind(bases)
    result.nodes.append(
        ComponentNode(
            id=node_id,
            name=name,
            stack=Stack.PYTHON,
            layer=layer,
            kind=kind,
            file_path=rel_path,
            annotations=annotations,
            fields=_dedupe_fields(fields),
            methods=methods,
        )
    )


def _collect_class_attribute(
    node: Node,
    owner_id: str,
    src: _Source,
    result: ParseResult,
    hints: dict[str, str],
) -> list[ComponentField]:
    left = node.child_by_field_name("left")
    if left is None or left.type != "identifier":
        return []

    name = src.text(left).strip()
    if not _FIELD_NAME_RE.match(name) or _DUNDER_RE.match(name):
        return []

    right = node.child_by_field_name("right")
    type_text = normalize_type(src.text(node.child_by_field_name("type")))
    call_name, call_args = _call_details(right, src)
    if not type_text and call_name:
        type_text = _infer_call_type(call_name, call_args, src)

    if not type_text:
        return []

    annotations = [f"@{call_name}"] if call_name in _FIELD_CALL_ANNOTATIONS else []
    _add_type_references(owner_id, type_text, result, hints, RelationType.DEPENDS_ON)

    if call_name == "relationship":
        target = _first_string_or_identifier(call_args, src)
        if target:
            result.references.append(ReferenceCandidate(owner_id, target, RelationType.REFERENCES))

    return [
        ComponentField(
            name=name,
            type=type_text,
            visibility="private" if name.startswith("_") else "public",
            annotations=annotations,
        )
    ]


def _collect_method(
    node: Node,
    owner_id: str,
    src: _Source,
    result: ParseResult,
    hints: dict[str, str],
) -> tuple[ComponentMethod, list[ComponentField]]:
    name = src.text(node.child_by_field_name("name")).strip()
    parameters, annotated_fields = _parameters(node, owner_id, src, result, hints)

    method = ComponentMethod(
        name=name,
        return_type=_return_type(node, src),
        parameters=parameters,
    )

    result.references.extend(
        ReferenceCandidate(owner_id, ref, RelationType.REFERENCES)
        for ref in _python_type_identifiers(method.return_type)
    )

    fields = annotated_fields if name == "__init__" else []
    fields.extend(_self_attributes(node, owner_id, src, result, hints) if name == "__init__" else [])
    return method, fields


def _parameters(
    node: Node,
    owner_id: str,
    src: _Source,
    result: ParseResult,
    hints: dict[str, str],
) -> tuple[list[str], list[ComponentField]]:
    params = node.child_by_field_name("parameters")
    rendered: list[str] = []
    annotated: list[ComponentField] = []
    if params is None:
        return rendered, annotated

    for param in params.children:
        if param.type not in {"identifier", "typed_parameter", "default_parameter", "typed_default_parameter"}:
            continue
        name = _parameter_name(param, src)
        if not name or name in {"self", "cls"}:
            continue
        type_text = normalize_type(src.text(param.child_by_field_name("type")))
        rendered.append(f"{name}: {type_text}" if type_text else name)
        if not type_text:
            continue

        depends = _has_depends(param, src)
        relation = RelationType.DEPENDS_ON if depends else RelationType.REFERENCES
        _add_type_references(owner_id, type_text, result, hints, relation)
        if _FIELD_NAME_RE.match(name):
            annotated.append(
                ComponentField(
                    name=name,
                    type=type_text,
                    visibility="private",
                    annotations=["@Depends"] if depends else [],
                )
            )

    return rendered, annotated


def _self_attributes(
    node: Node,
    owner_id: str,
    src: _Source,
    result: ParseResult,
    hints: dict[str, str],
) -> list[ComponentField]:
    """Annotated ``self.x`` attributes declared inside ``__init__``."""
    body = node.child_by_field_name("body")
    if body is None:
        return []

    annotated_params = {
        _parameter_name(child, src): normalize_type(src.text(child.child_by_field_name("type")))
        for child in (node.child_by_field_name("parameters").children if node.child_by_field_name("parameters") else [])
        if child.type in {"typed_parameter", "typed_default_parameter"}
    }

    attributes: list[ComponentField] = []
    for item in _statements(body):
        left = item.child_by_field_name("left")
        if item.type != "assignment" or left is None or left.type != "attribute":
            continue
        text = src.text(left).strip()
        if not text.startswith("self."):
            continue
        attribute = text.split(".", 1)[1]
        if not _FIELD_NAME_RE.match(attribute) or _DUNDER_RE.match(attribute):
            continue
        type_text = normalize_type(src.text(item.child_by_field_name("type")))
        if not type_text:
            right = item.child_by_field_name("right")
            name = src.text(right).strip() if right is not None and right.type == "identifier" else ""
            type_text = annotated_params.get(name, "")
        if not type_text:
            continue
        _add_type_references(owner_id, type_text, result, hints, RelationType.DEPENDS_ON)
        attributes.append(
            ComponentField(
                name=attribute,
                type=type_text,
                visibility="private",
                annotations=[],
            )
        )
    return attributes


def _parameter_name(param: Node, src: _Source) -> str:
    if param.type == "identifier":
        return src.text(param).strip()
    name_node = param.child_by_field_name("name")
    if name_node is not None:
        return src.text(name_node).strip()
    for child in param.children:
        if child.type == "identifier":
            return src.text(child).strip()
    return ""


def _has_depends(param: Node, src: _Source) -> bool:
    value = param.child_by_field_name("value")
    if value is None or value.type != "call":
        return False
    function = value.child_by_field_name("function")
    return base_type_name(src.text(function)) == "Depends"


def _return_type(node: Node, src: _Source) -> str | None:
    text = normalize_type(src.text(node.child_by_field_name("return_type")))
    return text or None


# ------------------------------------------------------------------------------- routers


def _collect_module_router(
    root: Node,
    rel_path: str,
    src: _Source,
    result: ParseResult,
    hints: dict[str, str],
) -> None:
    router_vars = _router_variables(root, src)
    view_module = _is_view_module(rel_path)
    if not router_vars and not view_module:
        return

    handlers: list[ComponentMethod] = []
    route_annotations: list[str] = [
        f"@{factory}" for factory in dict.fromkeys(router_vars.values())
    ]

    for candidate in _statements(root):
        definition, decorators = _definition(candidate, src)
        if definition is None or definition.type != "function_definition":
            continue
        routes = [
            decorator
            for decorator in decorators
            if _is_route_decorator(decorator, router_vars, rel_path)
        ]
        if not routes:
            continue
        route_annotations.extend(routes)
        method, _fields = _collect_method(definition, rel_path, src, result, hints)
        handlers.append(method)

    if not handlers:
        return

    for statement in _statements(root):
        if statement.type != "call":
            continue
        function = statement.child_by_field_name("function")
        if function is None or function.type != "attribute":
            continue
        target = function.child_by_field_name("object")
        method = function.child_by_field_name("attribute")
        if (
            target is None
            or target.type != "identifier"
            or src.text(target).strip() not in router_vars
            or src.text(method).strip() not in {"include_router", "register_blueprint"}
        ):
            continue
        arguments = statement.child_by_field_name("arguments")
        for argument in arguments.children if arguments is not None else []:
            if argument.type != "identifier":
                continue
            name = src.text(argument).strip()
            hint = hints.get(name)
            if hint is not None:
                result.references.append(
                    ReferenceCandidate(rel_path, name, RelationType.REFERENCES, hint)
                )

    result.nodes.append(
        ComponentNode(
            id=rel_path,
            name=_router_name(rel_path),
            stack=Stack.PYTHON,
            layer=Layer.CONTROLLER,
            kind=NodeKind.ROUTER,
            file_path=rel_path,
            annotations=dedupe(route_annotations),
            fields=[],
            methods=handlers,
        )
    )


def _router_variables(root: Node, src: _Source) -> dict[str, str]:
    variables: dict[str, str] = {}
    for statement in _statements(root):
        definition, _ = _definition(statement, src)
        if definition is None or definition.type != "assignment":
            continue
        left = definition.child_by_field_name("left")
        right = definition.child_by_field_name("right")
        if left is None or left.type != "identifier" or right is None or right.type != "call":
            continue
        factory = base_type_name(src.text(right.child_by_field_name("function")))
        if factory in _ROUTER_FACTORIES:
            variables[src.text(left).strip()] = factory
    return variables


def _is_route_decorator(decorator: str, router_vars: dict[str, str], rel_path: str) -> bool:
    target = decorator.lstrip("@").split("(", 1)[0]
    if "." in target:
        owner, _, method = target.rpartition(".")
        return owner.split(".")[-1] in router_vars and method in _ROUTER_DECORATORS
    return target in _DJANGO_VIEW_DECORATORS or (
        target in _ROUTER_DECORATORS and posixpath.basename(rel_path).startswith(("views", "routes"))
    )


def _router_name(rel_path: str) -> str:
    stem = posixpath.splitext(posixpath.basename(rel_path))[0]
    folder = posixpath.basename(posixpath.dirname(rel_path))
    if stem in _GENERIC_ROUTE_STEMS:
        labels = {
            "views": "Views",
            "urls": "Urls",
            "endpoints": "Endpoints",
            "routes": "Routes",
            "api": "Routes",
            "__init__": "Routes",
        }
        base = folder or stem
        return f"{_pascal(base)}{labels.get(stem, 'Routes')}"
    return _pascal(stem)


def _is_view_module(rel_path: str) -> bool:
    return posixpath.splitext(posixpath.basename(rel_path))[0].lower() in {
        "views",
        "routes",
        "urls",
        "endpoints",
    }


# ------------------------------------------------------------------------------- helpers


def _statements(node: Node) -> list[Node]:
    """Logical statements of a module/block, unwrapping ``expression_statement`` wrappers."""
    statements: list[Node] = []
    for child in node.children:
        if child.type == "expression_statement":
            statements.append(child.children[0] if child.children else child)
        elif child.type in {
            "decorated_definition",
            "class_definition",
            "function_definition",
            "import_statement",
            "import_from_statement",
        }:
            statements.append(child)
    return statements


def _definition(statement: Node, src: _Source) -> tuple[Node | None, list[str]]:
    if statement.type == "decorated_definition":
        definition = statement.child_by_field_name("definition")
        decorators = [
            _normalize_decorator(child, src) for child in statement.children if child.type == "decorator"
        ]
        return definition, [item for item in decorators if item]
    if statement.type in {"class_definition", "function_definition", "assignment"}:
        return statement, []
    return None, []


def _normalize_decorator(node: Node, src: _Source) -> str:
    text = src.text(node).strip().lstrip("@").split("(", 1)[0].strip()
    return f"@{text}" if text else ""


def _base_names(node: Node, src: _Source) -> list[str]:
    superclasses = node.child_by_field_name("superclasses")
    if superclasses is None:
        return []
    names: list[str] = []
    for child in superclasses.children:
        if child.type in {"(", ")", ",", "keyword_argument"}:
            continue
        name = base_type_name(src.text(child))
        if name:
            names.append(name)
    return dedupe(names)


def _call_details(node: Node | None, src: _Source) -> tuple[str, Node | None]:
    if node is None or node.type != "call":
        return "", None
    return base_type_name(src.text(node.child_by_field_name("function"))), node.child_by_field_name("arguments")


def _infer_call_type(call_name: str, arguments: Node | None, src: _Source) -> str:
    if call_name in _ORM_FIELD_TYPES:
        return _ORM_FIELD_TYPES[call_name]
    if call_name in {"mapped_column", "Column"} and arguments is not None:
        for child in arguments.children:
            if child.type in {"identifier", "attribute"}:
                return _COLUMN_TYPE_ALIASES.get(base_type_name(src.text(child)), "")
    return ""


def _first_string_or_identifier(arguments: Node | None, src: _Source) -> str:
    if arguments is None:
        return ""
    for child in arguments.children:
        if child.type == "string":
            return src.text(child).strip("'\"").split(".")[0]
        if child.type == "identifier":
            return src.text(child).strip()
    return ""


def _add_type_references(
    owner_id: str,
    type_text: str,
    result: ParseResult,
    hints: dict[str, str],
    relation: RelationType,
) -> None:
    for name in _python_type_identifiers(type_text):
        result.references.append(ReferenceCandidate(owner_id, name, relation, hints.get(name)))


def _python_type_identifiers(type_text: str | None) -> list[str]:
    return [name for name in type_identifiers(type_text or "") if name not in _PYTHON_NON_TYPES]


def _dedupe_fields(fields: list[ComponentField]) -> list[ComponentField]:
    seen: set[str] = set()
    unique: list[ComponentField] = []
    for field in fields:
        if field.name in seen:
            continue
        seen.add(field.name)
        unique.append(field)
    return unique


def _module_id(rel_path: str) -> str:
    parts = rel_path[: -len(".py")].split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(re.sub(r"[^A-Za-z0-9_]", "_", part) for part in parts)


def _pascal(value: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        return "Routes"
    return "".join(part[:1].upper() + part[1:] for part in parts)


__all__ = ["parse_python"]
