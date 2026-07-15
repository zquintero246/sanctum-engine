# Codex & Seals

*Every superstep presses a Seal into wax; the Codex is the ledger that
keeps them.*

Technically: a **Seal** is a checkpoint written at the end of each
superstep — the full Aether, the *next* frontier (exactly what resumption
must execute), the superstep number, a timestamp, metadata, and a unique
`seal_id`. A **Codex** stores Seals per Invocation:

```python
from sanctum.codex import MemoryCodex, SqliteCodex  # PostgresCodex: [postgres] extra

codex = SqliteCodex("rituals.db")
rite = ritual.compile(codex=codex)
await rite.ainvoke({"text": "lux"}, invocation_id="inv-1")
```

What an attached Codex enables:

- **Resumption** — `await rite.ainvoke(invocation_id="inv-1")` (no
  input) restores the latest Seal and continues from its frontier.
- **Human-in-the-loop** — a Sigil calls `interrupt()`; the aborted
  frontier is sealed and re-executes on resumption, with new data
  injected via `updates={...}`. Full walkthrough in the
  [guide](../guides/human-in-the-loop.md).
- **Time-travel** — `seal_id=...` resumes from any historic Seal.
  Histories are append-only: replays append new Seals rather than
  rewriting the past, leaving an honest audit trail.

Implementations: `MemoryCodex` (tests, ephemeral), `SqliteCodex` (one
local file, stdlib only), `PostgresCodex` (optional `[postgres]` extra).
SQLite/Postgres serialize the Aether as JSON — non-serializable values
raise `SealError` at write time with guidance; this keeps Seals portable
and inspectable with any tooling.
