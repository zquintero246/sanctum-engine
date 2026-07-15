# Wards

*Protective circles drawn around the ritual: nothing crosses them
unexamined.*

Technically: a **Ward** is middleware with four optional async hooks,
registered with `compile(wards=[...])` and applied as a **pipeline in
registration order** — each Ward's output delta is the next one's input:

```python
class Ward:
    def on_compile(self, manifest): ...                 # graph structure
    async def before_sigil(self, name, aether): ...
    async def after_sigil(self, name, aether, delta):   # transform or veto
        return delta
    async def on_omen(self, omen): ...                  # every engine event
```

The delta returned by `after_sigil` is what reducers, Seals, and
`SigilCompleted` Omens see. Raising `WardRejection` vetoes the delta: a
`DeltaRejected` Omen is emitted, the superstep aborts, and the Sigil's
`on_error` policy applies when present. `on_omen` sees every Omen even
without `astream` — build metrics and tracing without touching the
engine.

## Built-ins

| Ward | Purpose |
|---|---|
| `AuditWard(path)` | One JSON Lines entry per applied delta (`timestamp`, `sigil`, `delta`) — a complete local audit trail |
| `UsageWard()` | Accumulates the Oracle `usage` counters that `summon` attaches to assistant messages; `.summary()` per Sigil and per Invocation |
| `RedactWard(patterns)` | Masks regex matches (API keys, emails) in every delta string *before* Seals and logs see them |

Order matters: place `RedactWard` before `AuditWard` so the audit trail
only ever contains masked content. `TraceRecorder`
([tracing guide](../guides/tracing.md)) is also a Ward.
