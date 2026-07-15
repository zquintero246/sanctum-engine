"""Wards — the protective circles drawn around the ritual.

Middleware. A Ward intercepts Sigil deltas before they merge into the
Aether (transform or veto via WardRejection) and observes every Omen,
enabling validation, auditing, redaction, and metrics to be composed
around the engine without modifying graph logic. Registered with
``compile(wards=[...])`` and applied as a pipeline in registration order.
Built-ins: AuditWard (JSONL trail), UsageWard (token/call tally),
RedactWard (pattern masking before Seals and logs).
"""

from sanctum.wards.audit import AuditWard
from sanctum.wards.core import Ward
from sanctum.wards.errors import WardRejection
from sanctum.wards.redact import RedactWard
from sanctum.wards.usage import UsageWard

__all__ = [
    "AuditWard",
    "RedactWard",
    "UsageWard",
    "Ward",
    "WardRejection",
]
