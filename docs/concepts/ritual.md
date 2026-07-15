# Ritual & Rite

*The Ritual is the circle being drawn; the Rite is the circle sealed and
ready to be performed.*

Technically: `Ritual` is the mutable **graph builder** and `Rite` the
immutable **executable plan** produced by `compile()`.

```python
ritual = Ritual(schema)          # optional AetherSchema
ritual.add_sigil("think", think, policy=SigilPolicy(timeout=30))
ritual.add_conditional_edge("think", router)
rite = ritual.compile(recursion_limit=25, codex=codex, wards=[...])
```

`compile()` validates before anything runs: an entry point exists, every
edge and `path_map` target names a bound Sigil, every Sigil is reachable
from START (fallbacks count), and none is a dead end. Violations raise
`RitualValidationError` naming the offender.

The Rite exposes the whole invocation surface:

- `await rite.ainvoke(input, invocation_id=...)` — run to completion.
- `rite.invoke(...)` — synchronous wrapper.
- `rite.astream(..., mode=...)` — the same run as a stream of
  [Omens](omens.md).
- Resumption and time-travel via `invocation_id` / `seal_id` / `updates`
  when a [Codex](codex.md) is attached.

Execution follows the BSP superstep loop: run the whole frontier
concurrently, merge deltas deterministically, evaluate edges, repeat
until the frontier is empty or holds only END — bounded by
`recursion_limit` (default 25, `RecursionLimitError` beyond it). Cycles
are legal and intended: Sanctum executes a **cyclic state graph**, not a
DAG. The full loop is specified in the
[architecture document](../architecture.md).
