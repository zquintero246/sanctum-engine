"""A Codex kept in a distant archive: PostgreSQL.

Durable Seal store for multi-process or remote deployments. This is an
optional module: it requires the `psycopg` (v3) driver, declared as the
``postgres`` extra (``pip install sanctum-engine[postgres]``). The import
is lazy — importing this module never fails; instantiating PostgresCodex
without psycopg installed raises ImportError with install instructions.

Same contract and limitation as SqliteCodex: the Aether, frontier, and
metadata are stored as JSONB, so every value must be JSON-serializable.

Schema (created automatically on first use):

    CREATE TABLE IF NOT EXISTS seals (
        id BIGSERIAL PRIMARY KEY,
        seal_id TEXT NOT NULL UNIQUE,
        invocation_id TEXT NOT NULL,
        superstep INTEGER NOT NULL,
        aether JSONB NOT NULL,
        frontier JSONB NOT NULL,
        timestamp DOUBLE PRECISION NOT NULL,
        metadata JSONB NOT NULL
    );
    CREATE INDEX IF NOT EXISTS seals_invocation_idx
        ON seals (invocation_id, id);
"""

from __future__ import annotations

import json
from typing import Any

from sanctum.codex.core import Codex, Seal
from sanctum.codex.errors import SealError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seals (
    id BIGSERIAL PRIMARY KEY,
    seal_id TEXT NOT NULL UNIQUE,
    invocation_id TEXT NOT NULL,
    superstep INTEGER NOT NULL,
    aether JSONB NOT NULL,
    frontier JSONB NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL,
    metadata JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS seals_invocation_idx
    ON seals (invocation_id, id);
"""


def _psycopg() -> Any:
    """Import psycopg lazily, with install guidance on failure."""
    try:
        import psycopg
    except ImportError as exc:
        raise ImportError(
            "PostgresCodex requires the optional dependency 'psycopg'; "
            "install it with: pip install sanctum-engine[postgres]"
        ) from exc
    return psycopg


class PostgresCodex(Codex):
    """Durable PostgreSQL ledger of Seals.

    Persists Seals via async psycopg connections opened per operation
    against `dsn` (e.g. ``postgresql://user:pass@host/db``). The schema is
    created on first use. Requires JSON-serializable Aether and metadata.
    """

    def __init__(self, dsn: str) -> None:
        _psycopg()  # fail fast, with guidance, if the driver is missing
        self._dsn = dsn
        self._schema_ready = False

    async def _connect(self) -> Any:
        """Open an async connection, creating the schema on first use."""
        connection = await _psycopg().AsyncConnection.connect(self._dsn)
        if not self._schema_ready:
            await connection.execute(_SCHEMA)
            await connection.commit()
            self._schema_ready = True
        return connection

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
                f"not JSON-serializable: {exc}. PostgresCodex requires the "
                "Aether and metadata to hold only JSON-serializable values."
            ) from exc
        connection = await self._connect()
        try:
            await connection.execute(
                "INSERT INTO seals (seal_id, invocation_id, superstep, "
                "aether, frontier, timestamp, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
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
            await connection.commit()
        finally:
            await connection.close()

    async def get(self, invocation_id: str) -> Seal | None:
        """Return the Invocation's most recently written Seal, or None."""
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                "SELECT seal_id, superstep, aether, frontier, timestamp, "
                "metadata FROM seals WHERE invocation_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (invocation_id,),
            )
            row = await cursor.fetchone()
        finally:
            await connection.close()
        return _row_to_seal(row) if row is not None else None

    async def list(self, invocation_id: str) -> list[Seal]:
        """Return the Invocation's full Seal history, oldest first."""
        connection = await self._connect()
        try:
            cursor = await connection.execute(
                "SELECT seal_id, superstep, aether, frontier, timestamp, "
                "metadata FROM seals WHERE invocation_id = %s "
                "ORDER BY id ASC",
                (invocation_id,),
            )
            rows = await cursor.fetchall()
        finally:
            await connection.close()
        return [_row_to_seal(row) for row in rows]


def _row_to_seal(row: tuple[Any, ...]) -> Seal:
    """Rehydrate a Seal from a seals-table row."""
    seal_id, superstep, aether, frontier, timestamp, metadata = row
    return Seal(
        aether=aether if isinstance(aether, dict) else json.loads(aether),
        frontier=frontier if isinstance(frontier, list) else json.loads(frontier),
        superstep=superstep,
        timestamp=timestamp,
        metadata=metadata if isinstance(metadata, dict) else json.loads(metadata),
        seal_id=seal_id,
    )
