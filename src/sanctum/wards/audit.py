"""A scribe that records every change the ritual makes.

Local audit trail: one JSON Lines entry per applied delta, no external
services. Each line is ``{"timestamp": epoch, "sigil": name, "delta":
{...}}``; non-JSON-serializable values are stringified rather than
breaking the ritual. Place an AuditWard *after* a RedactWard in the
pipeline so the trail only ever contains redacted content.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sanctum.aether import Aether
from sanctum.wards.core import Ward


class AuditWard(Ward):
    """The ledger of deltas, written line by line to a local file.

    Appends one JSON object per Sigil delta to `path` (created on first
    write). Writes are synchronous appends of small lines — adequate for
    local-first auditing; use one file per Invocation for clean trails.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    async def after_sigil(
        self, name: str, aether: Aether, delta: dict[str, Any]
    ) -> dict[str, Any]:
        """Record the delta with a timestamp; pass it through unchanged."""
        entry = {"timestamp": time.time(), "sigil": name, "delta": delta}
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        return delta
