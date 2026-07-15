"""Sanctum — the chamber where rituals of invocation are prepared and performed.

A minimal, local-first orchestration engine for AI agents. Sanctum executes
cyclic state graphs by supersteps (Pregel/BSP model): Sigils (nodes) run in
parallel over a shared Aether (state), their partial deltas are merged through
each Conduit's reducer, and conditional edges decide the next active set until
END or the recursion limit is reached.
"""

from sanctum.aether import AetherSchema, AetherValidationError, Conduit
from sanctum.codex import Codex, Seal, SealError
from sanctum.grimoire import (
    Spell,
    SpellCallParseError,
    SpellExecutionError,
    Tome,
    spell,
    summon,
)
from sanctum.oracle import Oracle
from sanctum.ritual import (
    END,
    START,
    Interrupt,
    RecursionLimitError,
    Rite,
    Ritual,
    RitualValidationError,
    SigilExecutionError,
    SigilPolicy,
    SigilTimeoutError,
    interrupt,
)
from sanctum.wards import Ward, WardRejection

__version__ = "0.2.0"

__all__ = [
    "END",
    "START",
    "AetherSchema",
    "AetherValidationError",
    "Codex",
    "Conduit",
    "Interrupt",
    "Oracle",
    "RecursionLimitError",
    "Rite",
    "Ritual",
    "RitualValidationError",
    "Seal",
    "SealError",
    "SigilExecutionError",
    "SigilPolicy",
    "SigilTimeoutError",
    "Spell",
    "SpellCallParseError",
    "SpellExecutionError",
    "Tome",
    "Ward",
    "WardRejection",
    "__version__",
    "interrupt",
    "spell",
    "summon",
]
