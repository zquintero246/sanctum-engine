"""The signs a ritual gives off as it unfolds.

Streaming event model. Every Omen is a frozen, keyword-only dataclass
stamped with an epoch timestamp at creation. The scheduler emits Omens at
each lifecycle point; ``Rite.astream`` filters them by mode:

- ``"updates"``: SigilCompleted — one Omen per finished Sigil, with its
  delta (emitted at real completion time, so parallel Sigils appear in
  completion order).
- ``"values"``: SuperstepCompleted — the full Aether after each superstep.
- ``"omens"``: the granular lifecycle — RiteBegan, SuperstepBegan,
  SigilBegan, SigilCompleted, SealWritten, RiteManifested.
- ``"tokens"``: TokenEmitted — intermediate payloads a Sigil pushes
  through its injected `writer` (e.g. Oracle tokens), streamed before the
  Sigil finishes.

Modes combine: pass a set/list of names to receive the union.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class Omen:
    """A sign given off by the ritual, stamped with its moment.

    Base class of every streaming event; `timestamp` is epoch seconds at
    creation.
    """

    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True, kw_only=True)
class RiteBegan(Omen):
    """The invocation has started."""

    invocation_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SuperstepBegan(Omen):
    """A superstep is about to run its frontier.

    `frontier` lists the active Sigils in insertion order.
    """

    superstep: int
    frontier: list[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class SigilBegan(Omen):
    """A Sigil has started executing within a superstep."""

    sigil: str
    superstep: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SigilRetried(Omen):
    """A Sigil faltered and is being attempted again.

    Emitted before each retry granted by the Sigil's policy. `attempt` is
    the retry number (1-based); `cause` is the repr of the failure that
    triggered it.
    """

    sigil: str
    superstep: int
    attempt: int
    cause: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SigilCompleted(Omen):
    """A Sigil finished and returned its partial delta.

    Emitted when the Sigil returns — before the superstep's deltas are
    merged into the Aether.
    """

    sigil: str
    superstep: int
    delta: dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class SuperstepCompleted(Omen):
    """A superstep's deltas were merged; `aether` is the full state."""

    superstep: int
    aether: dict[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class SealWritten(Omen):
    """A Seal was inscribed in the Codex at the end of a superstep."""

    seal_id: str
    superstep: int


@dataclass(frozen=True, slots=True, kw_only=True)
class TokenEmitted(Omen):
    """A Sigil pushed an intermediate payload through its `writer`.

    Streams while the Sigil is still running — this is how Oracle tokens
    reach the consumer without waiting for the superstep to finish.
    """

    sigil: str
    superstep: int
    token: Any


@dataclass(frozen=True, slots=True, kw_only=True)
class RiteManifested(Omen):
    """The invocation concluded; `aether` is the final state."""

    aether: dict[str, Any]
    superstep: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DeltaRejected(Omen):
    """A Ward vetoed a Sigil's delta before it reached the Aether.

    Emitted when ``Ward.after_sigil`` raises WardRejection: the delta is
    discarded, the superstep aborts, and the Sigil's `on_error` policy
    applies if present. `ward` is the vetoing Ward's class name.
    """

    sigil: str
    superstep: int
    ward: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SpellCallRepaired(Omen):
    """A garbled spell call was mended locally before casting.

    Emitted by the summon loop's repair layer when a malformed call
    (broken JSON, fenced blocks, prose around the payload) was recovered
    without consulting the Oracle again. `detail` describes the mend.
    """

    spell: str
    detail: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SpellCallRejected(Omen):
    """A spell call could not be executed; the Oracle was asked to correct.

    Emitted by the summon loop's repair layer when a call is unparseable,
    names an unknown Spell, or carries invalid arguments. `reason` is the
    correction message injected into the transcript for the Oracle.
    """

    spell: str
    reason: str


STREAM_MODES: dict[str, tuple[type[Omen], ...]] = {
    "updates": (SigilCompleted,),
    "values": (SuperstepCompleted,),
    "tokens": (TokenEmitted,),
    "omens": (
        RiteBegan,
        SuperstepBegan,
        SigilBegan,
        SigilRetried,
        SigilCompleted,
        SealWritten,
        RiteManifested,
        SpellCallRepaired,
        SpellCallRejected,
        DeltaRejected,
    ),
}
"""The Omen classes each ``astream`` mode yields."""


def resolve_modes(mode: str | Iterable[str]) -> tuple[type[Omen], ...]:
    """Translate ``astream``'s `mode` into the Omen classes to yield.

    Accepts a single mode name or an iterable of names; combined modes
    yield the union of their Omen classes.

    Raises:
        ValueError: If a mode name is unknown or no mode is given.
    """
    names = [mode] if isinstance(mode, str) else list(mode)
    kinds: list[type[Omen]] = []
    for name in names:
        try:
            classes = STREAM_MODES[name]
        except KeyError:
            raise ValueError(
                f"Unknown astream mode '{name}'; valid modes: "
                f"{sorted(STREAM_MODES)}."
            ) from None
        for cls in classes:
            if cls not in kinds:
                kinds.append(cls)
    if not kinds:
        raise ValueError(
            f"astream requires at least one mode; valid modes: "
            f"{sorted(STREAM_MODES)}."
        )
    return tuple(kinds)
