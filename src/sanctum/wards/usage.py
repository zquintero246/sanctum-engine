"""A tally of every consultation the Oracle grants.

Token and call accounting without external services. Oracle-consulting
Sigils attach the Oracle's `usage` counters to the messages they append
(``summon`` does this automatically when the OracleResponse carries
usage); this Ward accumulates them per Sigil and for the whole
Invocation. Create one UsageWard per Invocation — or call ``reset()`` —
to keep totals meaningful.
"""

from __future__ import annotations

from typing import Any

from sanctum.aether import Aether
from sanctum.wards.core import Ward


class UsageWard(Ward):
    """The tally-keeper of Oracle calls and tokens.

    Scans each delta's ``messages`` for entries carrying a ``usage``
    mapping and accumulates the counters. ``summary()`` reports the totals
    per Sigil and for the Invocation.
    """

    def __init__(self) -> None:
        self._by_sigil: dict[str, dict[str, int]] = {}

    async def after_sigil(
        self, name: str, aether: Aether, delta: dict[str, Any]
    ) -> dict[str, Any]:
        """Accumulate usage counters found in the delta; pass it through."""
        messages = delta.get("messages")
        if isinstance(messages, list):
            for message in messages:
                usage = message.get("usage") if isinstance(message, dict) else None
                if not usage:
                    continue
                counters = self._by_sigil.setdefault(name, {"calls": 0})
                counters["calls"] += 1
                for key, value in usage.items():
                    counters[key] = counters.get(key, 0) + int(value)
        return delta

    def summary(self) -> dict[str, Any]:
        """Report accumulated usage: total and per Sigil.

        Returns ``{"total": {counters..., "calls": n}, "by_sigil":
        {sigil: {counters...}}}``.
        """
        total: dict[str, int] = {"calls": 0}
        for counters in self._by_sigil.values():
            for key, value in counters.items():
                total[key] = total.get(key, 0) + value
        return {
            "total": total,
            "by_sigil": {name: dict(c) for name, c in self._by_sigil.items()},
        }

    def reset(self) -> None:
        """Forget every counter (e.g. between Invocations)."""
        self._by_sigil.clear()
