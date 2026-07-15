"""Omens — the signs revealed while the ritual unfolds.

Streaming events. An Omen is a typed dataclass carrying a timestamp, emitted
by the engine as execution progresses (superstep boundaries, Sigil starts and
completions, Oracle tokens). Consumed through `astream` and suitable for
transports such as Server-Sent Events.
"""

from sanctum.omens.events import (
    STREAM_MODES,
    DeltaRejected,
    Omen,
    RiteBegan,
    RiteManifested,
    SealWritten,
    SigilBegan,
    SigilCompleted,
    SigilRetried,
    SpellCallRejected,
    SpellCallRepaired,
    SuperstepBegan,
    SuperstepCompleted,
    TokenEmitted,
    resolve_modes,
)

# tracing imports sanctum.wards, whose core imports Omen back from this
# package — safe ONLY because the events import above runs first, so the
# partially-initialized package already exposes Omen. Keep this order.
from sanctum.omens.tracing import TraceRecorder, render_trace

__all__ = [
    "STREAM_MODES",
    "DeltaRejected",
    "Omen",
    "RiteBegan",
    "RiteManifested",
    "SealWritten",
    "SigilBegan",
    "SigilCompleted",
    "SigilRetried",
    "SpellCallRejected",
    "SpellCallRepaired",
    "SuperstepBegan",
    "SuperstepCompleted",
    "TokenEmitted",
    "TraceRecorder",
    "render_trace",
    "resolve_modes",
]
