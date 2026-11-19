"""Deterministic Phase 2 audit engine. Rules operate on the Core IR only — nothing is written."""

from app.audit import rules as _rules  # noqa: F401  (import registers every rule)
from app.audit.context import AuditContext
from app.audit.engine import audit_rule, registered_rules, run_audit

__all__ = [
    "AuditContext",
    "audit_rule",
    "registered_rules",
    "run_audit",
]
