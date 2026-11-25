"""Compiler/test output parsing for the ephemeral builder (Phase 9).

Builders emit plain text on a shared stdout/stderr stream, so every diagnostic is recovered with
one of three fixed, defensive patterns (Maven, MSBuild and ``tsc``). Paths are normalized back to
workspace-relative form because the container always sees the snapshot at ``/workspace``.
"""

from __future__ import annotations

import re

from app.builders.models import BuildDiagnostic

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MAX_DIAGNOSTICS = 200

_MAVEN = re.compile(
    r"^\s*\[(?P<sev>ERROR|WARNING)\]\s+(?P<path>/workspace/\S+?):\[(?P<line>\d+),(?P<col>\d+)\]\s*(?P<msg>.*)$"
)
_MSBUILD = re.compile(
    r"(?P<path>(?:/workspace/)?[^\s:()]+\.cs)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<sev>error|warning)\s+(?P<code>[A-Za-z]{2,6}\d{3,5}):\s*(?P<msg>.*)$",
    re.IGNORECASE,
)
_TSC_PAREN = re.compile(
    r"(?P<path>[^\s()]+\.(?:ts|tsx|mts|cts|js|jsx|mjs|cjs))\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.*)$",
    re.IGNORECASE,
)
_TSC_COLON = re.compile(
    r"(?P<path>[^\s:]+\.(?:ts|tsx|mts|cts|js|jsx|mjs|cjs)):(?P<line>\d+):(?P<col>\d+)\s*[-–]\s*"
    r"(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.*)$",
    re.IGNORECASE,
)
_RUFF = re.compile(
    r"^(?P<path>[^\s:]+\.py):(?P<line>\d+):(?P<col>\d+):\s+(?P<code>[A-Z]+\d+)\s+(?P<msg>.*)$"
)
_MYPY = re.compile(
    r"^(?P<path>[^\s:]+\.py):(?P<line>\d+)(?::(?P<col>\d+))?:\s+(?P<sev>error|warning|note):\s*"
    r"(?P<msg>.*)$",
    re.IGNORECASE,
)

_PARSERS_BY_STACK = {
    "java": (_MAVEN,),
    "csharp": (_MSBUILD,),
    "nodejs": (_TSC_PAREN, _TSC_COLON),
    "python": (_RUFF, _MYPY),
}
_ALL_PARSERS = (_MAVEN, _MSBUILD, _TSC_PAREN, _TSC_COLON, _RUFF, _MYPY)


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text or "")


def normalize_output(text: str) -> str:
    """ANSI-free, CRLF-free build output; used for the response body and the AI prompt excerpt."""
    cleaned = strip_ansi(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return cleaned.strip()


def normalize_path(raw: str) -> str:
    path = (raw or "").strip().replace("\\", "/")
    if path.startswith("/workspace/"):
        path = path[len("/workspace/") :]
    elif path == "/workspace":
        path = ""
    while path.startswith("./"):
        path = path[2:]
    return path


def parse_diagnostics(output: str, stack: str | None = None) -> list[BuildDiagnostic]:
    """Parse combined build output into stable, deduplicated diagnostics."""
    parsers = _PARSERS_BY_STACK.get(stack or "", _ALL_PARSERS)
    diagnostics: list[BuildDiagnostic] = []
    seen: set[tuple[str, int, int, str, str, str]] = set()

    for raw_line in strip_ansi(output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for pattern in parsers:
            match = pattern.search(line)
            if match is None:
                continue
            groups = match.groupdict()
            severity = (groups.get("sev") or "").lower()
            if severity == "note":
                break
            diagnostic = BuildDiagnostic(
                file_path=normalize_path(groups.get("path") or ""),
                line=int(groups.get("line") or 0),
                column=int(groups.get("col") or 0),
                severity="warning" if severity == "warning" else "error",
                code=(groups.get("code") or "").strip(),
                message=(groups.get("msg") or "").strip(),
            )
            key = (
                diagnostic.file_path,
                diagnostic.line,
                diagnostic.column,
                diagnostic.severity,
                diagnostic.code,
                diagnostic.message,
            )
            if key not in seen:
                seen.add(key)
                diagnostics.append(diagnostic)
                if len(diagnostics) >= MAX_DIAGNOSTICS:
                    return diagnostics
            break

    return diagnostics


__all__ = ["MAX_DIAGNOSTICS", "normalize_output", "normalize_path", "parse_diagnostics", "strip_ansi"]
