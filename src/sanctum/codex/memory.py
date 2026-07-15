"""A Codex written in breath: it fades when the session ends.

In-memory Seal store, the reference implementation for tests and
ephemeral invocations. Not shared across processes and not persistent.
"""

from __future__ import annotations

from sanctum.codex.core import Codex, Seal


class MemoryCodex(Codex):
    """Ephemeral in-memory ledger of Seals.

    Stores histories in a plain dict keyed by `invocation_id`. Intended
    for tests and short-lived local runs; contents vanish with the object.
    """

    def __init__(self) -> None:
        self._seals: dict[str, list[Seal]] = {}

    async def put(self, invocation_id: str, seal: Seal) -> None:
        """Append a Seal to the Invocation's history."""
        self._seals.setdefault(invocation_id, []).append(seal)

    async def get(self, invocation_id: str) -> Seal | None:
        """Return the Invocation's most recently written Seal, or None."""
        history = self._seals.get(invocation_id)
        return history[-1] if history else None

    async def list(self, invocation_id: str) -> list[Seal]:
        """Return the Invocation's full Seal history, oldest first."""
        return list(self._seals.get(invocation_id, ()))
