# Aether & Conduits

*The Aether is the shared energy every summoned entity draws upon; a
Conduit is one channel it flows through.*

Technically: the Aether is a flat `dict[str, Any]` — the shared state.
An `AetherSchema` maps each key to a **Conduit**, which declares the
**reducer** `(current, update) -> new` used to merge Sigil deltas into
that key.

```python
from typing import Annotated
from sanctum import AetherSchema, Conduit, Ritual
from sanctum.aether import add, append

schema = AetherSchema({
    "messages": Conduit(reducer=append),   # lists concatenate
    "score": Annotated[int, add],          # numbers accumulate
    "verdict": str,                        # plain type -> overwrite
})
ritual = Ritual(schema)
```

Built-in reducers: `overwrite` (default), `append`, `add`, `merge_dict`;
any callable with the same signature works (e.g. `max`).

Rules worth knowing:

- **Unknown keys are rejected at runtime** — a delta (or initial input)
  writing outside the schema raises `AetherValidationError` naming the
  offending Sigil.
- **Missing keys skip the reducer**: the first write to an absent key is
  assigned directly, so custom reducers never receive a missing
  `current`.
- **Determinism**: within a superstep, deltas apply in Sigil *insertion
  order* (the order they were bound), so concurrent writes to the same
  Conduit resolve identically on every run.
- Without a schema, deltas merge by plain `dict.update` — a deliberate
  low-friction mode for prototypes.
- `__errors__` is reserved for the engine (see
  [resilience policies](policies.md)).
