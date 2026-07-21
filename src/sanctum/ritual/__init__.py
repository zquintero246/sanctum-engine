"""Ritual — the preparation and performance of the invocation.

Graph construction and execution. A Ritual is the graph builder: Sigils
(nodes) are bound with `add_sigil`, connected with `add_edge` and
`add_conditional_edge`, and `compile()` produces a Rite — the executable
plan. The scheduler runs the Rite by supersteps: execute active Sigils in
parallel, collect deltas, apply reducers deterministically, evaluate edges,
write a Seal, and repeat until END or `recursion_limit`.
"""

from sanctum.ritual.constants import DEFAULT_RECURSION_LIMIT, END, START
from sanctum.ritual.core import Aether, Rite, Ritual
from sanctum.ritual.errors import (
    RecursionLimitError,
    RitualValidationError,
    SigilExecutionError,
    SigilJoinError,
    SigilTimeoutError,
)
from sanctum.ritual.interrupt import Interrupt, interrupt
from sanctum.ritual.policies import BackoffFn, SigilPolicy, exponential_backoff
from sanctum.ritual.scheduler import RouterFn, Scheduler, SigilFn

__all__ = [
    "DEFAULT_RECURSION_LIMIT",
    "END",
    "START",
    "Aether",
    "BackoffFn",
    "Interrupt",
    "RecursionLimitError",
    "Rite",
    "Ritual",
    "RitualValidationError",
    "RouterFn",
    "Scheduler",
    "SigilExecutionError",
    "SigilFn",
    "SigilJoinError",
    "SigilPolicy",
    "SigilTimeoutError",
    "exponential_backoff",
    "interrupt",
]
