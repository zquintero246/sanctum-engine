# Omens & streaming

*The ritual gives off signs as it unfolds; read them as they appear.*

Technically: an **Omen** is a frozen, timestamped dataclass emitted at
every engine lifecycle point. `Rite.astream()` yields them live, filtered
by combinable modes:

```python
async for omen in rite.astream(input, mode={"updates", "tokens"}):
    ...
```

| Mode | Yields |
|---|---|
| `"updates"` (default) | `SigilCompleted` — one per finished Sigil, with its delta |
| `"values"` | `SuperstepCompleted` — the full Aether after each superstep |
| `"tokens"` | `TokenEmitted` — payloads a Sigil pushes through its `writer`, while it runs |
| `"omens"` | The granular lifecycle: `RiteBegan`, `SuperstepBegan`, `SigilBegan`, `SigilRetried`, `SigilCompleted`, `SealWritten`, `RiteManifested`, plus `SpellCallRepaired` / `SpellCallRejected` / `DeltaRejected` |

## Live tokens from inside a Sigil

Declare a `writer` parameter and the engine injects an async callable:

```python
async def chant(aether, writer):
    async for chunk in oracle.stream_generate(aether["messages"]):
        await writer(chunk)          # TokenEmitted, delivered immediately
    return {"chanted": True}
```

Passing an Omen instance to `writer` emits it verbatim — Sigils and
libraries can define custom observability events without touching the
engine.

Semantics worth knowing: `SigilCompleted` is emitted at *real* completion
time (parallel Sigils appear in completion order — truthful
observability), while state still merges deterministically in insertion
order. Exceptions propagate to the stream consumer after the emitted
Omens drain; closing the generator early cancels the Invocation. For
bridging to Server-Sent Events, see
[`examples/sse_flask.py`](https://github.com/zquintero246/sanctum-engine/blob/main/examples/sse_flask.py);
for recording everything to a file, see [Tracing](../guides/tracing.md).
