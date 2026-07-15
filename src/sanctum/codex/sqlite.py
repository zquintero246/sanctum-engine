"""A Codex bound in a single local volume: one SQLite file.

Durable Seal store on the Python stdlib `sqlite3` module — no external
dependencies, local-first. The Aether, frontier, and metadata are stored
as JSON columns.

Limitation: every value in the Aether and metadata must be
JSON-serializable (str, int, float, bool, None, and lists/dicts thereof).
Non-serializable state raises SealError at `put` time; convert rich
objects to plain data in your Sigils, or use MemoryCodex.

The interface is async to honor the Codex contract, but operations execute
synchronously inline: local SQLite calls are short-lived and this keeps
the core dependency-free.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from sanctum.codex.core import Codex, Seal
from sanctum.codex.errors import SealError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seals (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    seal_id TEXT NOT NULL UNIQUE,
    invocation_id TEXT NOT NULL,
    superstep INTEGER NOT NULL,
    aether TEXT NOT NULL,
    frontier TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS seals_invocation_idx
    ON seals (invocation_id, rowid);
"""


class SqliteCodex(Codex):
    """Durable single-file ledger of Seals.

    Persists Seals to a SQLite database at `path`, creating the file and
    schema on first use. Recreating the object over the same path sees the
    same history. Requires JSON-serializable Aether and metadata (see the
    module docstring).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        with closing(sqlite3.connect(self._path)) as connection:
            connection.executescript(_SCHEMA)
            connection.commit()

    async def put(self, invocation_id: str, seal: Seal) -> None:
        """Append a Seal to the Invocation's history.

        Raises:
            SealError: If the Seal's Aether, frontier, or metadata cannot
                be serialized to JSON.
        """
        try:
            aether = json.dumps(seal.aether)
            frontier = json.dumps(seal.frontier)
            metadata = json.dumps(seal.metadata)
        except (TypeError, ValueError) as exc:
            raise SealError(
                f"Seal '{seal.seal_id}' of Invocation '{invocation_id}' is "
                f"not JSON-serializable: {exc}. SqliteCodex requires the "
                "Aether and metadata to hold only JSON-serializable values."
            ) from exc
        with closing(sqlite3.connect(self._path)) as connection:
            connection.execute(
                "INSERT INTO seals (seal_id, invocation_id, superstep, "
                "aether, frontier, timestamp, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    seal.seal_id,
                    invocation_id,
                    seal.superstep,
                    aether,
                    frontier,
                    seal.timestamp,
                    metadata,
                ),
            )
            connection.commit()

    async def get(self, invocation_id: str) -> Seal | None:
        """Return the Invocation's most recently written Seal, or None."""
        with closing(sqlite3.connect(self._path)) as connection:
            row = connection.execute(
                "SELECT seal_id, superstep, aether, frontier, timestamp, "
                "metadata FROM seals WHERE invocation_id = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (invocation_id,),
            ).fetchone()
        return _row_to_seal(row) if row is not None else None

    async def list(self, invocation_id: str) -> list[Seal]:
        """Return the Invocation's full Seal history, oldest first."""
        with closing(sqlite3.connect(self._path)) as connection:
            rows = connection.execute(
                "SELECT seal_id, superstep, aether, frontier, timestamp, "
                "metadata FROM seals WHERE invocation_id = ? "
                "ORDER BY rowid ASC",
                (invocation_id,),
            ).fetchall()
        return [_row_to_seal(row) for row in rows]


def _row_to_seal(row: tuple[Any, ...]) -> Seal:
    """Rehydrate a Seal from a seals-table row."""
    seal_id, superstep, aether, frontier, timestamp, metadata = row
    return Seal(
        aether=json.loads(aether),
        frontier=json.loads(frontier),
        superstep=superstep,
        timestamp=timestamp,
        metadata=json.loads(metadata),
        seal_id=seal_id,
    )
