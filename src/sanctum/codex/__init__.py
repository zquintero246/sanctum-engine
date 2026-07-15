"""Codex — the ledger where every step of the ritual is inscribed.

Persistence and checkpointing. A Seal is the snapshot of the Aether taken at
the end of each superstep; a Codex stores and retrieves Seals per Invocation
(execution session, keyed by `invocation_id`). Implementations: MemoryCodex,
SqliteCodex, and PostgresCodex (optional extra, lazy imports; import it
explicitly from `sanctum.codex.postgres`).
"""

from sanctum.codex.core import Codex, Seal
from sanctum.codex.errors import SealError
from sanctum.codex.memory import MemoryCodex
from sanctum.codex.sqlite import SqliteCodex

__all__ = [
    "Codex",
    "MemoryCodex",
    "Seal",
    "SealError",
    "SqliteCodex",
]
