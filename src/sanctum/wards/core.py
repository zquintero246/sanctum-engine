"""The protective circles drawn around the ritual.

Middleware interface. A Ward observes and intercepts the engine's work
through three optional async hooks, all no-ops by default:

- ``before_sigil(name, aether)``: called before a Sigil executes.
- ``after_sigil(name, aether, delta) -> delta``: called with the Sigil's
  delta before it merges into the Aether — return it (possibly
  transformed), or raise WardRejection to veto it. Transformed deltas are
  what Seals, Omens, and downstream Wards see.
- ``on_omen(omen)``: called for every Omen the engine emits, before it
  reaches the stream — build tracing/metrics here without touching the
  engine.

Wards are registered with ``compile(wards=[...])`` and applied as a
pipeline in registration order: the delta returned by one Ward is the
input of the next.
"""

from __future__ import annotations

from typing import Any

from sanctum.aether import Aether
from sanctum.omens import Omen


class Ward:
    """One circle of protection: observe, transform, or veto.

    Subclass and override any hook; the defaults observe nothing and pass
    deltas through unchanged. Hooks run inside the superstep, so keep them
    fast — offload heavy work.
    """

    def on_compile(self, manifest: dict[str, Any]) -> None:
        """Called once when the Ward is bound to a compiled graph.

        `manifest` describes the graph: ``{"sigils": [names], "edges":
        {source: [targets]}, "conditional_edges": {source: [targets] or
        ["*"] when dynamic}}``. Treat it as read-only. Lets observability
        Wards (e.g. TraceRecorder) know the structure they are watching.
        """

    async def before_sigil(self, name: str, aether: Aether) -> None:
        """Called before Sigil `name` executes (aether is a copy)."""

    async def after_sigil(
        self, name: str, aether: Aether, delta: dict[str, Any]
    ) -> dict[str, Any]:
        """Inspect or transform Sigil `name`'s delta; return the delta.

        The returned mapping replaces the Sigil's delta for everything
        downstream (next Wards, reducers, Seals, SigilCompleted Omens).

        Raises:
            WardRejection: To veto the delta (see the class docstring).
        """
        return delta

    async def on_omen(self, omen: Omen) -> None:
        """Called for every Omen before it reaches the stream."""
