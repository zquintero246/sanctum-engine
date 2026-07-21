"""The ways a ritual may be refused or go wrong while performed.

Exceptions raised by the Ritual layer.
"""

from typing import Any


class RitualValidationError(Exception):
    """The Ritual is malformed and cannot be sealed into a Rite.

    Raised while building or compiling a Ritual whose graph is invalid:
    missing entry point, edges referencing unknown Sigils, Sigils
    unreachable from START, or Sigils without an outgoing edge.
    """


class RecursionLimitError(Exception):
    """The ritual spun past its allotted supersteps and was cut short.

    Raised by a Rite when an Invocation exceeds the Rite's
    ``recursion_limit`` supersteps without reaching END — typically a cycle
    whose stop condition never triggers. The message includes the
    `invocation_id` and the last Sigil executed.
    """


class SigilExecutionError(Exception):
    """A Sigil failed mid-ritual and the superstep was abandoned.

    Raised when a Sigil raises during a superstep: the sibling Sigils of
    that superstep are cancelled and none of its deltas are applied.
    Carries the offending Sigil's name (`sigil`), a snapshot of the Aether
    at the moment of failure (`aether`), and the original exception as
    ``__cause__``.
    """

    def __init__(self, message: str, *, sigil: str, aether: dict[str, Any]) -> None:
        super().__init__(message)
        self.sigil = sigil
        self.aether = aether


class SigilJoinError(Exception):
    """The rite concluded while a join still awaited absent celebrants.

    Raised when an Invocation's frontier empties while one or more
    ``join="all"`` Sigils are still waiting for static predecessors that
    will never run — typically because a router steered a feeding branch
    away from the join. `pending` maps each waiting Sigil to the sorted
    list of predecessors it is still missing.
    """

    def __init__(self, message: str, *, pending: dict[str, list[str]]) -> None:
        super().__init__(message)
        self.pending = pending


class SigilTimeoutError(SigilExecutionError):
    """A Sigil pondered past its allotted time and was cut off.

    Raised when an attempt exceeds its SigilPolicy's `timeout`. Subclass
    of SigilExecutionError, so generic failure handling (retries with the
    default `retry_on`, `on_error` fallbacks, caller except clauses)
    covers timeouts too. `timeout` carries the configured bound in
    seconds.
    """

    def __init__(
        self, message: str, *, sigil: str, aether: dict[str, Any], timeout: float
    ) -> None:
        super().__init__(message, sigil=sigil, aether=aether)
        self.timeout = timeout
