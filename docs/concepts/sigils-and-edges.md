# Sigils & edges

*A Sigil is one inscription in the circle: a single, bounded act of the
ritual.*

Technically: a Sigil is a **node** — any callable, sync or async, with
the signature `(aether: dict) -> dict`. It receives a copy of the full
Aether and returns a *partial delta*; only the delta changes state
(mutating the argument has no effect — BSP isolation).

```python
async def think(aether):
    answer = await oracle.generate(aether["messages"])
    return {"messages": [{"role": "assistant", "content": answer.text}]}

ritual.add_sigil("think", think)
```

A Sigil that declares a `writer` parameter receives an async callable:
`await writer(token)` streams tokens out while the Sigil still runs (see
[Omens](omens.md)).

## Edges

- **Static** — `add_edge(source, target)`: after `source`, `target`
  activates. A source may carry several static edges: all targets run in
  the next superstep (**fan-out**). `set_entry_point(name)` is sugar for
  `add_edge(START, name)`.
- **Conditional** — `add_conditional_edge(source, router, path_map=None)`:
  `router(aether) -> str` picks the next Sigil (or END) against the
  post-superstep state; `path_map` optionally translates router outputs
  to Sigil names. Routing back to an earlier Sigil is how agentic loops
  are built.

Static and conditional edges are mutually exclusive on the same source.
**Fan-in** uses "any" semantics by default: a Sigil runs as soon as any
predecessor activates it, and multiple activations within one superstep
coalesce into a single execution.

## Wait-all joins

*Some Sigils refuse to act until every celebrant has arrived.*

`add_sigil(name, fn, join="all")` turns a Sigil into a **barrier** over
its static predecessors: activations accumulate — across supersteps when
converging branches have uneven lengths — and the Sigil runs exactly once,
when the last predecessor signals it. Pending activations are recorded in
each Seal's metadata (reserved key `__join_pending__`), so resumption and
time-travel preserve the barrier's progress.

```python
ritual.add_sigil("synthesize", synthesize, join="all")
ritual.add_edge("scout_papers", "synthesize")
ritual.add_edge("scout_web", "synthesize")      # runs once, after both
```

Three rules keep joins sound (all checked at compile time): a `join="all"`
Sigil needs at least one static incoming edge, cannot be the target of a
conditional edge (a router's activation cannot satisfy a barrier), and
cannot serve as an `on_error` fallback. If a feeding branch never runs —
typically because an upstream router steered away — the Invocation ends
with `SigilJoinError` naming the missing predecessors. Trade-offs in the
[architecture document](../architecture.md).

## Circles

*A sealed rite may be drawn whole inside another's circle.*

`circle(rite, name=..., input_map=..., output_map=...)` mounts a compiled
Rite as a **single Sigil** (a subgraph as a node). Each activation runs a
complete inner Invocation; `input_map` projects the outer Aether into the
inner input, `output_map` projects the inner result back as this Sigil's
delta (dicts `{inner: outer}` / `{outer: inner}`, or callables). Every
inner Omen is echoed to the outer stream as `CircleEchoed(circle=name,
omen=...)`, and an inner failure surfaces as a failure of the Circle's
own Sigil — so its `SigilPolicy` governs the whole subgraph.

```python
entity = summon(oracle, tome, role="You are a scryer.")
ritual.add_sigil("scryer", circle(
    entity,
    name="scryer",
    input_map=lambda a: {"messages": [{"role": "user", "content": a["quest"]}]},
    output_map=lambda f: {"report": f["messages"][-1]["content"]},
))
```

Each activation is a fresh inner Invocation (inner Seals do not resume
across outer supersteps — attach a Codex to the *outer* Rite for
persistence), and an inner `interrupt()` surfaces as a Circle failure
rather than an outer interrupt.
