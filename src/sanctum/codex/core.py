"""Seals — the wax impressions each superstep leaves behind.

Checkpoint model and storage contract. A Seal is the snapshot written at
the end of a superstep: the full Aether, the frontier of the next
superstep, the superstep number, a timestamp, and free-form metadata. A
Codex stores Seals per Invocation (keyed by `invocation_id`) and yields
them back to enable resumption, human-in-the-loop pauses, and time-travel.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Seal:
    """The wax impression of one superstep.

    Immutable checkpoint. `aether` is the full state after the superstep's
    deltas were applied; `frontier` the Sigils active in the *next*
    superstep — resumption continues from it; `superstep` the 1-based
    count within the Invocation; `timestamp` epoch seconds; `metadata`
    free-form context (e.g. interrupt details). `seal_id` uniquely
    identifies the Seal for time-travel.
    """

    aether: dict[str, Any]
    frontier: list[str]
    superstep: int
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    seal_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class Codex(ABC):
    """The ledger where Seals are inscribed and consulted.

    Abstract async storage contract for Seals, keyed by `invocation_id`.
    Histories are append-only: resuming an Invocation appends new Seals
    after the old ones, and `get` returns the most recently written Seal
    (not the highest superstep number). Implementations: MemoryCodex
    (ephemeral, for tests), SqliteCodex (local file), PostgresCodex
    (optional extra, `sanctum.codex.postgres`).
    """

    @abstractmethod
    async def put(self, invocation_id: str, seal: Seal) -> None:
        """Append a Seal to the Invocation's history."""

    @abstractmethod
    async def get(self, invocation_id: str) -> Seal | None:
        """Return the Invocation's most recently written Seal, or None."""

    @abstractmethod
    async def list(self, invocation_id: str) -> list[Seal]:
        """Return the Invocation's full Seal history, oldest first."""
