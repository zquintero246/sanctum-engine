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
**Fan-in** uses "any" semantics: a Sigil runs as soon as any predecessor
activates it, and multiple activations within one superstep coalesce into
a single execution ("wait for all" is future work — trade-offs in the
[architecture document](../architecture.md)).
