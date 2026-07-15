"""Aether — the shared energy all invoked entities draw upon.

Shared state management. The Aether is a typed dict whose channels are
Conduits, each declaring a reducer (overwrite, append, add, merge_dict, or
custom) that merges the partial deltas returned by Sigils. An AetherSchema
defines the Conduits available to a Ritual.
"""

from sanctum.aether.core import Aether, AetherSchema, Conduit
from sanctum.aether.errors import AetherValidationError
from sanctum.aether.reducers import Reducer, add, append, merge_dict, overwrite

__all__ = [
    "Aether",
    "AetherSchema",
    "AetherValidationError",
    "Conduit",
    "Reducer",
    "add",
    "append",
    "merge_dict",
    "overwrite",
]
