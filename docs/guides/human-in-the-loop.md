# Human-in-the-loop with `interrupt()`

*The ritual pauses, the circle stays drawn, and the world outside is
asked to speak.*

A Sigil calls `interrupt()` to pause the Invocation. The current
superstep is aborted (its deltas discarded), a Seal is written pointing
at the aborted frontier, and `Interrupt` propagates to your code. Later —
seconds or days — you resume with the same `invocation_id`, injecting the
human's answer through `updates`; the interrupted frontier re-executes
and finds the data in the Aether.

```python
from sanctum import END, Interrupt, Ritual, interrupt
from sanctum.codex import SqliteCodex

def review(aether):
    if not aether.get("approved"):
        interrupt("awaiting editorial approval")
    return {"reviewed": True}

ritual = Ritual()
ritual.add_sigil("draft", lambda a: {"draft": a["topic"] + "..."})
ritual.add_sigil("review", review)
ritual.add_sigil("publish", lambda a: {"published": a["draft"].upper()})
ritual.set_entry_point("draft")
ritual.add_edge("draft", "review")
ritual.add_edge("review", "publish")
ritual.add_edge("publish", END)
rite = ritual.compile(codex=SqliteCodex("reviews.db"))

try:
    await rite.ainvoke({"topic": "the aether", "approved": False},
                       invocation_id="post-42")
except Interrupt as pause:
    print(f"paused at '{pause.sigil}': {pause.reason}")
    # ... show the draft to a human, wait for their verdict ...

result = await rite.ainvoke(invocation_id="post-42",
                            updates={"approved": True})
```

Rules that make this reliable:

- The interrupting Sigil **re-executes on resumption** — it must check
  the Aether to decide whether the awaited data has arrived (that's what
  the `approved` check does). Sigils sharing its superstep should be
  idempotent, since they may run twice.
- The interrupt Seal's metadata records `{"interrupted": True, "sigil",
  "reason"}` — inspect it with `await codex.get(invocation_id)`.
- With an `AetherSchema`, `updates` merges through the Conduit reducers
  and unknown keys are rejected.

Runnable version: `examples/human_in_the_loop/`.
