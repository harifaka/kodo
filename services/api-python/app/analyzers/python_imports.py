"""Importable module index and ``from … import …`` resolution for the Python analyzer.

Kept separate from the AST walk so import resolution stays testable and the analyzer module stays
focused on component extraction.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable, Iterable

from tree_sitter import Node

TextReader = Callable[[Node | None], str]


class ModuleIndex:
    """Maps importable dotted module paths to workspace-relative files (package-root aware)."""

    def __init__(self, known_files: Iterable[str]) -> None:
        self._files = set(known_files)
        self._packages = {
            posixpath.dirname(path)
            for path in self._files
            if posixpath.basename(path) == "__init__.py"
        }
        self._modules: dict[str, str] = {}
        for path in sorted(self._files):
            for dotted in self._module_candidates(path):
                self._modules.setdefault(dotted, path)

    def _module_candidates(self, path: str) -> list[str]:
        parts = path[: -len(".py")].split("/")
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            return []
        candidates = [".".join(parts)]
        start = next(
            (
                index
                for index in range(len(parts) - 1)
                if "/".join(parts[: index + 1]) in self._packages
                and (index == 0 or "/".join(parts[:index]) not in self._packages)
            ),
            None,
        )
        if start is not None:
            candidates.append(".".join(parts[start:]))
        return [candidate for candidate in dict.fromkeys(candidates) if candidate]

    def file_for(self, dotted: str) -> str | None:
        path = self._modules.get(dotted)
        if path is None or posixpath.basename(path) == "__init__.py":
            return None
        return path


def import_hints(
    root: Node,
    module_id: str,
    known_files: Iterable[str],
    text: TextReader,
) -> dict[str, str]:
    """Map locally imported symbol names to the workspace file that defines them."""
    index = ModuleIndex(known_files)
    hints: dict[str, str] = {}

    for statement in root.children:
        if statement.type == "import_from_statement":
            target = _resolve_from_module(statement, module_id, index, text)
            if target is None:
                continue
            for child in statement.children:
                if child.type not in {"dotted_name", "aliased_import"}:
                    continue
                local = text(child).split(" as ")[-1].strip()
                hints[local.split(".")[-1]] = target
        elif statement.type == "import_statement":
            for child in statement.children:
                if child.type not in {"dotted_name", "aliased_import"}:
                    continue
                raw = text(child).strip()
                imported, _, alias = raw.partition(" as ")
                target = index.file_for(imported.strip())
                if target is None:
                    continue
                local = alias.strip() or imported.strip().split(".")[0]
                hints[local] = target

    return hints


def _resolve_from_module(
    statement: Node,
    module_id: str,
    index: ModuleIndex,
    text: TextReader,
) -> str | None:
    module_node = statement.child_by_field_name("module_name")
    if module_node is None:
        return None
    raw = text(module_node).strip()
    if module_node.type != "relative_import":
        return index.file_for(raw)

    dots = len(raw) - len(raw.lstrip("."))
    remainder = raw[dots:]
    parts = module_id.split(".")[:-1]
    up = dots - 1
    parts = parts[: len(parts) - up] if up <= len(parts) else []
    if remainder:
        parts = [*parts, *remainder.split(".")]
    return index.file_for(".".join(parts))


__all__ = ["ModuleIndex", "import_hints"]
