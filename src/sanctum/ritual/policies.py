"""Wards of endurance: what to do when a Sigil falters.

Per-Sigil resilience policies. A local model can stall, a Spell can flake
— the engine must not hang or die for it. A SigilPolicy bounds each
attempt with a timeout, retries transient failures with exponential
backoff and jitter, and can divert a definitive failure to a fallback
Sigil instead of failing the Invocation.

Precedence on failure (documented contract):

1. **timeout** bounds every attempt — an attempt past it raises
   SigilTimeoutError (a SigilExecutionError subclass);
2. **retries** re-run the Sigil when the failure matches `retry_on`
   (timeouts included by default), emitting a SigilRetried Omen per
   attempt and sleeping `backoff(attempt)` seconds between them;
3. **on_error** — once retries are exhausted, jump to the named fallback
   Sigil: the failed superstep is aborted (no Seal written, sibling
   deltas discarded), the failure is appended to the reserved
   ``"__errors__"`` Conduit, and the fallback runs as the next superstep
   (which writes its Seal normally);
4. otherwise the failure propagates as **SigilExecutionError**.

Timeouts bound *async* Sigils; a synchronous Sigil body cannot be
interrupted mid-run — offload blocking work with ``asyncio.to_thread``.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

BackoffFn = Callable[[int], float]
"""Delay in seconds before retry number `attempt` (1-based)."""


def exponential_backoff(
    base: float = 0.1, cap: float = 5.0, jitter: bool = True
) -> BackoffFn:
    """Build the classic exponential-backoff-with-jitter delay function.

    Retry `attempt` waits ``min(cap, base * 2**(attempt-1))`` seconds,
    scaled by a uniform factor in [0.5, 1.0] when `jitter` is on (jitter
    decorrelates retry storms when several Sigils fail together).
    """

    def delay(attempt: int) -> float:
        value = min(cap, base * (2 ** (attempt - 1)))
        if jitter:
            value *= random.uniform(0.5, 1.0)
        return value

    return delay


_DEFAULT_BACKOFF = exponential_backoff()


@dataclass(frozen=True, slots=True)
class SigilPolicy:
    """The endurance granted to one Sigil.

    `timeout` bounds each attempt in seconds (None = unbounded);
    `retries` is how many extra attempts follow a matching failure;
    `backoff` maps the retry number to a delay in seconds (default:
    exponential with jitter, base 0.1s, cap 5s); `retry_on` is the tuple
    of exception types worth retrying (default: any Exception — includes
    SigilTimeoutError); `on_error` names the fallback Sigil to jump to
    after the last attempt fails (see the module docstring for the full
    precedence and Seal interaction).

    Attach per Sigil with ``add_sigil(name, fn, policy=...)`` or globally
    with ``compile(default_policy=...)``; the per-Sigil policy wins.
    """

    timeout: float | None = None
    retries: int = 0
    backoff: BackoffFn = field(default=_DEFAULT_BACKOFF)
    retry_on: tuple[type[Exception], ...] = (Exception,)
    on_error: str | None = None
