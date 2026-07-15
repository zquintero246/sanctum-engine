"""The Conduits are drawn: the shape the shared energy must take.

State schema. A Conduit declares how one key of the Aether merges deltas
(its reducer); an AetherSchema is the complete set of Conduits a Ritual
operates on. When a Ritual has a schema, every delta key must name a
declared Conduit and is merged through that Conduit's reducer instead of
plain overwrite.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from sanctum.aether.errors import AetherValidationError
from sanctum.aether.reducers import Reducer, overwrite

Aether = dict[str, Any]
"""The shared state dict, keyed by Conduit name."""


@dataclass(frozen=True, slots=True)
class Conduit:
    """One channel of the Aether and the way it merges new energy.

    Declares the reducer ``(current, update) -> new`` applied when a
    Sigil's delta writes to this key. Defaults to `overwrite`. The reducer
    is skipped when the key is not yet present in the Aether: the delta
    value is set directly, so custom reducers never receive a missing
    current value.
    """

    reducer: Reducer = overwrite


def _as_conduit(value: Conduit | Any) -> Conduit:
    """Coerce a schema declaration into a Conduit.

    Accepts a Conduit instance, an ``Annotated[T, reducer]`` (the first
    callable metadata item becomes the reducer), or any plain type
    (overwrite). Types themselves are not enforced at runtime; the schema
    governs keys and reducers.
    """
    if isinstance(value, Conduit):
        return value
    if get_origin(value) is Annotated:
        for item in get_args(value)[1:]:
            if callable(item):
                return Conduit(reducer=item)
    return Conduit()


class AetherSchema:
    """The declared shape of the shared energy.

    Maps each Aether key to its Conduit. Values in the constructor mapping
    may be Conduit instances, ``Annotated[T, reducer]`` forms, or plain
    types (which default to overwrite):

        AetherSchema({
            "messages": Conduit(reducer=append),
            "score": Annotated[int, add],
            "verdict": str,
        })

    Delta application is deterministic: within a superstep, deltas are
    applied in Sigil insertion order (the order Sigils were bound to the
    Ritual), and each key merges through its Conduit's reducer.
    """

    def __init__(self, conduits: Mapping[str, Conduit | Any]) -> None:
        self._conduits: dict[str, Conduit] = {
            name: _as_conduit(value) for name, value in conduits.items()
        }

    @classmethod
    def from_class(cls, source: type) -> AetherSchema:
        """Read the Conduits from a class's annotations.

        Sugar for declaring the schema as an annotated class::

            class ChantAether:
                messages: Annotated[list, append]
                score: int  # plain annotation -> overwrite

        ``Annotated[T, reducer]`` fields use the first callable metadata
        item as the Conduit's reducer.
        """
        hints = get_type_hints(source, include_extras=True)
        return cls(hints)

    @property
    def conduits(self) -> dict[str, Conduit]:
        """A copy of the mapping from Aether key to its Conduit."""
        return dict(self._conduits)

    def __contains__(self, key: str) -> bool:
        return key in self._conduits

    def validate_input(self, input: Mapping[str, Any]) -> None:
        """Check that the initial Aether only uses declared Conduits.

        Raises:
            AetherValidationError: If `input` contains keys not declared in
                the schema.
        """
        unknown = sorted(set(input) - set(self._conduits))
        if unknown:
            raise AetherValidationError(
                f"Invocation input contains unknown Conduit(s): "
                f"{', '.join(unknown)}; declared Conduits: "
                f"{', '.join(sorted(self._conduits)) or '(none)'}."
            )

    def apply_delta(
        self, aether: Mapping[str, Any], delta: Mapping[str, Any], *, sigil: str
    ) -> Aether:
        """Merge one Sigil's delta into the Aether through the Conduits.

        Each delta key must name a declared Conduit; its value merges via
        the Conduit's reducer, or is set directly when the key is not yet
        present. Returns a new dict; `aether` is not mutated.

        Args:
            aether: Current state.
            delta: Partial update returned by the Sigil.
            sigil: Name of the Sigil that produced the delta, for error
                attribution.

        Raises:
            AetherValidationError: If the delta writes to a key not
                declared in the schema; the message names the Sigil.
        """
        merged: Aether = dict(aether)
        for key, update in delta.items():
            if key not in self._conduits:
                raise AetherValidationError(
                    f"Sigil '{sigil}' wrote to unknown Conduit '{key}'; "
                    f"declared Conduits: "
                    f"{', '.join(sorted(self._conduits)) or '(none)'}."
                )
            if key in merged:
                merged[key] = self._conduits[key].reducer(merged[key], update)
            else:
                merged[key] = update
        return merged

    def apply_deltas(
        self,
        aether: Mapping[str, Any],
        deltas: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> Aether:
        """Merge one superstep's deltas into the Aether, deterministically.

        Deltas are applied strictly in the order given as ``(sigil_name,
        delta)`` pairs; the engine passes them in Sigil insertion order
        (the order Sigils were bound to the Ritual). This makes concurrent
        writes to the same Conduit within a superstep deterministic: the
        Conduit's reducer folds each delta in, in that fixed order.
        Returns a new dict; `aether` is not mutated.
        """
        merged: Aether = dict(aether)
        for sigil, delta in deltas:
            merged = self.apply_delta(merged, delta, sigil=sigil)
        return merged
