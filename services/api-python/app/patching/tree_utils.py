"""Byte-offset helpers shared by the Tree-sitter patchers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node


def node_text(source: bytes, node: Node | None) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def line_start(source: bytes, offset: int) -> int:
    index = source.rfind(b"\n", 0, offset)
    return 0 if index < 0 else index + 1


def line_end(source: bytes, offset: int) -> int:
    """Offset of the newline that terminates the line, or len(source) when there is none."""
    index = source.find(b"\n", offset)
    return len(source) if index < 0 else index


def line_removal_end(source: bytes, offset: int) -> int:
    """End offset that also consumes the line terminator (including a preceding CR)."""
    end = line_end(source, offset)
    if end < len(source):
        end += 1
    return end


def line_indent(source: bytes, offset: int) -> str | None:
    """Leading whitespace of the line containing `offset`, or None when the line has content first."""
    start = line_start(source, offset)
    prefix = source[start:offset]
    if prefix.strip(b" \t") == b"":
        return prefix.decode("utf-8", errors="replace")
    return None


def line_ending(source: bytes) -> str:
    return "\r\n" if b"\r\n" in source else "\n"


def splice(source: bytes, edits: list[tuple[int, int, bytes]]) -> bytes:
    """Apply non-overlapping (start, end, replacement) edits, back to front."""
    result = source
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def indent_with(base: str, extra: str = "    ") -> str:
    return f"{base}{extra}"


@dataclass(frozen=True)
class MemberIndent:
    text: str
    explicit: bool


def detect_member_indent(source: bytes, body: Node, fallback_base: str) -> MemberIndent:
    """Indent of the first member in a body, or base indent + four spaces."""
    for child in body.children:
        if child.type in {"{", "}"}:
            continue
        indent = line_indent(source, child.start_byte)
        if indent is not None:
            return MemberIndent(indent, True)
    return MemberIndent(indent_with(fallback_base), False)


def detect_type_indent(source: bytes, node: Node) -> str:
    indent = line_indent(source, node.start_byte)
    return indent if indent is not None else ""


def find_line_insertion_after(source: bytes, node: Node) -> int:
    """Offset of the newline that follows `node`'s line (insert before it)."""
    return line_end(source, node.end_byte)
