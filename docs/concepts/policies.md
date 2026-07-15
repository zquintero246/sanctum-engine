# Resilience policies

*Wards of endurance: the ritual does not hang because a model sat
thinking, and does not die because a Spell flaked.*

Technically: a `SigilPolicy` grants one Sigil (or, via
`compile(default_policy=...)`, all of them) bounded execution and
recovery. The per-Sigil policy wins.

```python
from sanctum import SigilPolicy
from sanctum.ritual import exponential_backoff

ritual.add_sigil("consult", consult, policy=SigilPolicy(
    timeout=30.0,                          # per attempt
    retries=2,
    backoff=exponential_backoff(base=0.5), # with jitter
    retry_on=(OracleTimeoutError, OracleConnectionError),
    on_error="fallback_answer",            # jump here after the last failure
))
```

## The precedence contract

1. **timeout** bounds each attempt (`asyncio.timeout`); past it,
   `SigilTimeoutError` — a `SigilExecutionError` subclass, so everything
   downstream treats it uniformly. Timeouts bound *async* Sigils; a sync
   body cannot be interrupted — offload with `asyncio.to_thread`.
2. **retries** re-run the Sigil when the failure matches `retry_on`
   (timeouts included by default), emitting a `SigilRetried` Omen per
   attempt and sleeping `backoff(attempt)` between them.
3. **on_error** — after the last attempt, the failed superstep is aborted
   (no Seal, sibling deltas discarded, the counter still advances so
   failure cycles stay bounded by `recursion_limit`), the failure is
   appended to the reserved `__errors__` Conduit as
   `{"sigil", "error", "type", "superstep"}`, and the named fallback
   Sigil runs as the next superstep — sealing normally.
4. Otherwise the failure propagates as **SigilExecutionError** (with the
   Sigil's name, an Aether snapshot, and the original as `__cause__`).

The fallback reads the failure from the Aether:

```python
def fallback_answer(aether):
    failure = aether["__errors__"][-1]
    return {"answer": f"degraded: {failure['error']}"}
```

`compile()` validates policies (positive timeout, existing `on_error`
target, no self-fallback) and counts fallbacks as reachability edges.
See `examples/resilient_pipeline/` for all three mechanisms in one run.
