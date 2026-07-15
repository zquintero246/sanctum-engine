"""A veil drawn over what must not be written down.

Redaction before persistence and observability. This Ward masks regex
matches (API keys, emails, ...) in every string of the delta *before* it
merges into the Aether — so Seals, the SigilCompleted Omens, downstream
Wards (place an AuditWard after it), and the final result only ever see
the masked text. It cannot redact what a Sigil already sent to an
external system; it guards Sanctum's own outputs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from sanctum.aether import Aether
from sanctum.wards.core import Ward


class RedactWard(Ward):
    """The veil over secrets: masks patterns in every delta string.

    `patterns` is an iterable of regex strings or compiled patterns; every
    match anywhere in the delta (recursing through dicts, lists, and
    tuples) is replaced by `mask`.
    """

    def __init__(
        self, patterns: Iterable[str | re.Pattern[str]], mask: str = "[REDACTED]"
    ) -> None:
        self._patterns = [re.compile(pattern) for pattern in patterns]
        self._mask = mask

    async def after_sigil(
        self, name: str, aether: Aether, delta: dict[str, Any]
    ) -> dict[str, Any]:
        """Return the delta with every pattern match masked."""
        return self._scrub(delta)

    def _scrub(self, value: Any) -> Any:
        """Recursively mask pattern matches in strings."""
        if isinstance(value, str):
            for pattern in self._patterns:
                value = pattern.sub(self._mask, value)
            return value
        if isinstance(value, dict):
            return {key: self._scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._scrub(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._scrub(item) for item in value)
        return value
